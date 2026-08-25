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
from sportsedge.ufc_closing_odds import enrich_metadata_with_closing_market, load_archive
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
    market_pairs = [
        (tr, meta)
        for tr, meta in pairs
        if _market_probability(meta) is not None
    ]
    market_rows = [tr for tr, _ in market_pairs]
    market_probs = [_market_probability(meta) for _, meta in market_pairs]
    market_ys = [tr.y_a_win for tr, _ in market_pairs]
    return {
        "model": _model_metrics(model, rows),
        "model_on_market": _model_metrics(model, market_rows),
        "market_no_vig": _probability_metrics(market_probs, market_ys),
    }


def _promotion_evidence(
    model,
    holdout_pairs,
    contract,
    bundle,
    *,
    closing_summary,
    closing_provenance_errors,
):
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
    model_on_market = slices["all"]["model_on_market"]
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
        or model_on_market.get("brier") is None
        or float(model_on_market["brier"])
        > float(all_market["brier"]) + float(contract["max_brier_delta_vs_market"])
    ):
        blockers.append("BRIER_VS_MARKET_GATE")
    if (
        all_market.get("log_loss") is None
        or model_on_market.get("log_loss") is None
        or float(model_on_market["log_loss"])
        > float(all_market["log_loss"])
        + float(contract["max_log_loss_delta_vs_market"])
    ):
        blockers.append("LOG_LOSS_VS_MARKET_GATE")

    last_training_day = datetime.strptime(bundle.last_fight_date, "%Y-%m-%d").date()
    evaluated_day = datetime.now(timezone.utc).date()
    training_age_days = max(0, (evaluated_day - last_training_day).days)
    if training_age_days > int(contract["training_data_max_age_days"]):
        blockers.append("TRAINING_DATA_STALE")

    closing_coverage = float(closing_summary.get("coverage") or 0.0)
    closing_coverage_min = float(contract["closing_market_coverage_min"])
    closing_baseline_verified = (
        not closing_provenance_errors
        and closing_coverage >= closing_coverage_min
        and int(closing_summary.get("matched") or 0) > 0
    )
    if (
        contract.get("closing_market_provenance_required", True)
        and closing_provenance_errors
    ):
        blockers.append("CLOSING_ODDS_PROVENANCE_UNVERIFIED")
    if closing_coverage < closing_coverage_min:
        blockers.append("CLOSING_MARKET_COVERAGE_INSUFFICIENT")

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
            "external_archive_supplied": bool(closing_summary.get("archive_supplied")),
            "provider": closing_summary.get("provider"),
            "source": closing_summary.get("source"),
            "sport_key": closing_summary.get("sport_key"),
            "no_vig_normalization": True,
            "closing_baseline_verified": closing_baseline_verified,
            "coverage": closing_coverage,
            "coverage_min": closing_coverage_min,
            "matched_holdout_fights": int(closing_summary.get("matched") or 0),
            "holdout_rows": int(closing_summary.get("rows") or 0),
            "min_bookmakers": int(contract["closing_market_min_bookmakers"]),
            "max_snapshot_lag_seconds": int(
                contract["closing_market_max_snapshot_lag_seconds"]
            ),
            "provenance_errors": list(closing_provenance_errors),
            "provenance_note": (
                "Verified closing evidence must come from the SportsEdge The Odds API "
                "historical archive contract. Prices are fight-matched, no-vig, "
                "multi-book, and timestamped at or before commence time."
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
    ap.add_argument(
        "--closing-odds",
        default="",
        help="Optional verified SportsEdge historical closing-odds archive JSON",
    )
    args = ap.parse_args()

    contract = json.loads(
        Path(args.promotion_contract).read_text(encoding="utf-8")
    )
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

    holdout_metadata = [dict(x) for x in bundle.metadata[holdout_start:]]
    closing_provenance_errors = ["CLOSING_ARCHIVE_NOT_SUPPLIED"]
    closing_summary = {
        "archive_supplied": False,
        "provider": None,
        "source": None,
        "sport_key": None,
        "rows": len(holdout_metadata),
        "matched": 0,
        "coverage": 0.0,
        "min_bookmakers": int(contract["closing_market_min_bookmakers"]),
        "mean_bookmakers": 0.0,
    }
    if args.closing_odds:
        max_lag = int(contract["closing_market_max_snapshot_lag_seconds"])
        archive_payload, closing_quotes, closing_provenance_errors = load_archive(
            args.closing_odds,
            max_lag_seconds=max_lag,
        )
        holdout_metadata, match_summary = enrich_metadata_with_closing_market(
            holdout_metadata,
            closing_quotes,
            min_bookmakers=int(contract["closing_market_min_bookmakers"]),
            max_lag_seconds=max_lag,
        )
        closing_summary = {
            **match_summary,
            "archive_supplied": True,
            "provider": archive_payload.get("provider"),
            "source": archive_payload.get("source"),
            "sport_key": archive_payload.get("sport_key"),
        }

    holdout_pairs = list(zip(rows[holdout_start:], holdout_metadata))
    promotion = _promotion_evidence(
        model,
        holdout_pairs,
        contract,
        bundle,
        closing_summary=closing_summary,
        closing_provenance_errors=closing_provenance_errors,
    )

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
