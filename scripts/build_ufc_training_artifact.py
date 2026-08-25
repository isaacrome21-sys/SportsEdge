#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from math import log
from pathlib import Path
from statistics import mean

from sportsedge.ufc_history import (
    DEFAULT_EVENT_URL,
    DEFAULT_FIGHTERS_URL,
    DEFAULT_RESULTS_URL,
    DEFAULT_STATS_URL,
    load_history_from_urls,
)
from sportsedge.ufc_training import evaluate, fit_chronological


def _probability_metrics(probs, ys, bins=10):
    pairs = [(float(p), int(y)) for p, y in zip(probs, ys) if p is not None]
    if not pairs:
        return {
            "n": 0,
            "log_loss": None,
            "brier": None,
            "accuracy": None,
            "calibration_error": None,
        }
    ps = [min(1.0 - 1e-12, max(1e-12, p)) for p, _ in pairs]
    labels = [y for _, y in pairs]
    ll = -mean(y * log(p) + (1 - y) * log(1 - p) for p, y in zip(ps, labels))
    brier = mean((p - y) ** 2 for p, y in zip(ps, labels))
    accuracy = mean(1.0 if (p >= 0.5) == bool(y) else 0.0 for p, y in zip(ps, labels))
    ce = 0.0
    for k in range(bins):
        lo, hi = k / bins, (k + 1) / bins
        idx = [
            i
            for i, p in enumerate(ps)
            if lo <= p < hi or (k == bins - 1 and p == 1.0)
        ]
        if idx:
            ce += (len(idx) / len(ps)) * abs(
                mean(ps[i] for i in idx) - mean(labels[i] for i in idx)
            )
    return {
        "n": len(ps),
        "log_loss": ll,
        "brier": brier,
        "accuracy": accuracy,
        "calibration_error": ce,
    }


def _model_metrics(model, rows):
    rows = list(rows)
    if not rows:
        return {
            "n": 0,
            "log_loss": None,
            "brier": None,
            "accuracy": None,
            "calibration_error": None,
        }
    return evaluate(model, rows).__dict__


def _market_probability(meta):
    value = meta.get("market_probability_a")
    if value is None:
        return None
    try:
        p = float(value)
    except (TypeError, ValueError):
        return None
    return p if 0.0 < p < 1.0 else None


def _slice_metrics(model, pairs):
    pairs = list(pairs)
    rows = [tr for tr, _ in pairs]
    market_probs = [_market_probability(meta) for _, meta in pairs]
    ys = [tr.y_a_win for tr, _ in pairs]
    return {
        "model": _model_metrics(model, rows),
        "market_no_vig": _probability_metrics(market_probs, ys),
    }


def _promotion_evidence(model, holdout_pairs, contract, bundle):
    slices = {
        "all": _slice_metrics(model, holdout_pairs),
        "ufc_debut_any": _slice_metrics(
            model,
            (
                pair
                for pair in holdout_pairs
                if min(
                    int(pair[1].get("fighter_a_experience") or 0),
                    int(pair[1].get("fighter_b_experience") or 0),
                )
                == 0
            ),
        ),
        "low_experience_any_le2": _slice_metrics(
            model,
            (
                pair
                for pair in holdout_pairs
                if min(
                    int(pair[1].get("fighter_a_experience") or 0),
                    int(pair[1].get("fighter_b_experience") or 0),
                )
                <= 2
            ),
        ),
        "male": _slice_metrics(
            model,
            (pair for pair in holdout_pairs if pair[1].get("gender") == "MALE"),
        ),
        "female": _slice_metrics(
            model,
            (pair for pair in holdout_pairs if pair[1].get("gender") == "FEMALE"),
        ),
        "three_round": _slice_metrics(
            model,
            (
                pair
                for pair in holdout_pairs
                if int(pair[1].get("scheduled_rounds") or 0) == 3
            ),
        ),
        "five_round": _slice_metrics(
            model,
            (
                pair
                for pair in holdout_pairs
                if int(pair[1].get("scheduled_rounds") or 0) == 5
            ),
        ),
        "market_a_favorite": _slice_metrics(
            model,
            (
                pair
                for pair in holdout_pairs
                if _market_probability(pair[1]) is not None
                and _market_probability(pair[1]) >= 0.5
            ),
        ),
        "market_a_underdog": _slice_metrics(
            model,
            (
                pair
                for pair in holdout_pairs
                if _market_probability(pair[1]) is not None
                and _market_probability(pair[1]) < 0.5
            ),
        ),
    }

    weight_classes = sorted(
        {
            str(meta.get("weight_class") or "")
            for _, meta in holdout_pairs
            if meta.get("weight_class")
        }
    )
    slices["weight_class"] = {
        wc: _slice_metrics(
            model,
            (pair for pair in holdout_pairs if pair[1].get("weight_class") == wc),
        )
        for wc in weight_classes
    }

    blockers = []
    all_model = slices["all"]["model"]
    all_market = slices["all"]["market_no_vig"]
    debut = slices["ufc_debut_any"]["model"]

    if int(all_model.get("n") or 0) < int(contract["holdout_n_min"]):
        blockers.append("HOLDOUT_N_INSUFFICIENT")
    if int(debut.get("n") or 0) < int(contract["debut_n_min"]):
        blockers.append("DEBUT_SLICE_N_INSUFFICIENT")
    if (
        all_model.get("calibration_error") is None
        or float(all_model["calibration_error"])
        > float(contract["calibration_error_max"])
    ):
        blockers.append("CALIBRATION_ERROR_GATE")

    if (
        all_market.get("brier") is None
        or all_model.get("brier") is None
        or float(all_model["brier"])
        > float(all_market["brier"]) + float(contract["max_brier_delta_vs_market"])
    ):
        blockers.append("BRIER_VS_MARKET_GATE")
    if (
        all_market.get("log_loss") is None
        or all_model.get("log_loss") is None
        or float(all_model["log_loss"])
        > float(all_market["log_loss"])
        + float(contract["max_log_loss_delta_vs_market"])
    ):
        blockers.append("LOG_LOSS_VS_MARKET_GATE")

    last_training_day = datetime.strptime(bundle.last_fight_date, "%Y-%m-%d").date()
    evaluated_day = datetime.now(timezone.utc).date()
    training_age_days = max(0, (evaluated_day - last_training_day).days)
    if training_age_days > int(contract["training_data_max_age_days"]):
        blockers.append("TRAINING_DATA_STALE")

    closing_baseline_verified = False
    if (
        contract.get("closing_market_provenance_required", True)
        and not closing_baseline_verified
    ):
        blockers.append("CLOSING_ODDS_PROVENANCE_UNVERIFIED")

    short_notice_slice_available = False
    if contract.get("short_notice_slice_required", True) and not short_notice_slice_available:
        blockers.append("SHORT_NOTICE_SLICE_UNAVAILABLE")

    blockers = list(dict.fromkeys(blockers))
    promoted = not blockers
    history_semantics = {
        "feature_time": "pre_fight_snapshot",
        "state_update": "after_result_and_stats",
        "current_fight_stats_in_current_row": False,
        "fight_level_source": True,
    }

    return {
        "schema_version": 2,
        "sport": "UFC",
        "promoted": promoted,
        "status": "PROMOTED" if promoted else "UNVERIFIED",
        "blockers": blockers,
        "contract": contract,
        "training_source": "Greco1899/scrape_ufc_stats UFCStats mirror",
        "training_sources": bundle.source_urls,
        "last_training_fight_date": bundle.last_fight_date,
        "training_freshness": {
            "evaluated_at_utc_date": evaluated_day.isoformat(),
            "age_days": training_age_days,
            "max_age_days": int(contract["training_data_max_age_days"]),
            "fresh": training_age_days <= int(contract["training_data_max_age_days"]),
        },
        "history_semantics": history_semantics,
        "market_baseline": {
            "available_in_training_source": False,
            "source_fields": [],
            "no_vig_normalization": False,
            "closing_baseline_verified": closing_baseline_verified,
            "provenance_note": (
                "Fresh UFCStats fight history contains no sportsbook prices. "
                "A separately joined, fight-matched closing-odds archive is required."
            ),
        },
        "short_notice_slice_available": short_notice_slice_available,
        "dwcs_specific_validation": {
            "status": "UNVERIFIED",
            "reason": (
                "Current UFCStats event history does not provide a historical DWCS "
                "training/holdout slice; UFC-debut validation is not treated as DWCS validation."
            ),
        },
        "slices": slices,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--event-url", default=DEFAULT_EVENT_URL)
    ap.add_argument("--results-url", default=DEFAULT_RESULTS_URL)
    ap.add_argument("--stats-url", default=DEFAULT_STATS_URL)
    ap.add_argument("--fighters-url", default=DEFAULT_FIGHTERS_URL)
    ap.add_argument("--min-date", default="2010-01-01")
    ap.add_argument("--output", default="models/ufc_logistic_v1.json")
    ap.add_argument("--metrics", default="artifacts/ufc_training_metrics.json")
    ap.add_argument(
        "--promotion-evidence", default="artifacts/ufc_promotion_evidence.json"
    )
    ap.add_argument(
        "--promotion-contract", default="config/ufc_promotion_contract_v1.json"
    )
    args = ap.parse_args()

    bundle = load_history_from_urls(
        event_url=args.event_url,
        results_url=args.results_url,
        stats_url=args.stats_url,
        fighters_url=args.fighters_url,
        min_date=args.min_date,
    )
    rows = bundle.training_rows
    if len(rows) < 1000:
        raise SystemExit(f"UFC_HISTORY_ROWS_INSUFFICIENT rows={len(rows)}")

    model, metrics = fit_chronological(rows)
    n = len(rows)
    train_end = max(1, int(n * 0.70))
    holdout_start = max(train_end + 1, int(n * 0.85))
    holdout_pairs = list(zip(rows[holdout_start:], bundle.metadata[holdout_start:]))

    contract = json.loads(Path(args.promotion_contract).read_text(encoding="utf-8"))
    promotion = _promotion_evidence(model, holdout_pairs, contract, bundle)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.metrics).parent.mkdir(parents=True, exist_ok=True)
    Path(args.promotion_evidence).parent.mkdir(parents=True, exist_ok=True)

    payload = model.as_dict()
    payload["training_source"] = promotion["training_source"]
    payload["training_sources"] = bundle.source_urls
    payload["training_rows"] = len(rows)
    payload["last_training_fight_date"] = bundle.last_fight_date
    payload["holdout_metrics"] = metrics.__dict__
    payload["promotion_status"] = promotion["status"]
    payload["history_semantics"] = promotion["history_semantics"]

    Path(args.output).write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    Path(args.metrics).write_text(
        json.dumps(metrics.__dict__, indent=2, sort_keys=True), encoding="utf-8"
    )
    Path(args.promotion_evidence).write_text(
        json.dumps(promotion, indent=2, sort_keys=True), encoding="utf-8"
    )

    print(
        json.dumps(
            {
                "rows": len(rows),
                "last_date": bundle.last_fight_date,
                "promotion_status": promotion["status"],
                "promotion_blockers": promotion["blockers"],
                **metrics.__dict__,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
