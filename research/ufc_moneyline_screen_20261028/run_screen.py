#!/usr/bin/env python3
"""UFC moneyline flagship — Leg 1 historical design screen.

Implements the validation protocol of
research/new_sports_designs_20261027/UFC_MONEYLINE_DESIGN_PREREG_DRAFT.md
section 6, Leg 1, with pass criteria read at run time from
config/ufc_promotion_contract_v1.json (adopted verbatim by the draft):

  fit <= 2019  ->  Platt calibration only on 2020-2022  ->  test 2023-2025

Construction under test: the existing engine's learner
(sportsedge.ufc_training.fit_logistic over its frozen FEATURES diffs,
features rebuilt point-in-time by sportsedge.ufc_history from the pinned
per-fight record). Market baseline: the pinned mdabbert recorded prices,
de-vigged, labeled RECORDED_PRICE_NOT_DK_CLOSE everywhere — the dataset
does not document book or timestamp, so these are recorded prices, not
timestamp-authenticated DraftKings closes. Odds are evaluation-only and
never enter the feature vector.

The draft's section 5 pre-screen audit runs before any fitting: the market
dataset's shipped career aggregates are compared against aggregates
rebuilt from the per-fight record. The construction uses rebuilt features
only; shipped aggregates are never used as features.

Usage:
  python3 run_screen.py --data-dir <dir with the five pinned CSVs> \
      [--pins PINS.json] [--contract config/ufc_promotion_contract_v1.json] \
      [--out screen_results.json]

Data files are NOT committed to the repo; they are pulled from the pinned
public mirrors (see PINS.json) and hash-verified before use.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import date, datetime
from math import log
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sportsedge.ufc_history import build_history_from_text, normalize_name
from sportsedge.ufc_training import (
    LogisticArtifact,
    TrainingRow,
    evaluate,
    fit_logistic,
    fit_platt,
)

PROVENANCE_LABEL = "RECORDED_PRICE_NOT_DK_CLOSE"

FIT_END = "2019-12-31"
CAL_START, CAL_END = "2020-01-01", "2022-12-31"
TEST_START, TEST_END = "2023-01-01", "2025-12-31"


# ---------------------------------------------------------------- pins ----

def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_pinned_files(data_dir: Path, pins: dict) -> dict[str, str]:
    """Read every pinned file from data_dir and verify size + sha256."""
    texts: dict[str, str] = {}
    for source_key in ("market_source", "per_fight_source"):
        for entry in pins[source_key]["files"]:
            path = data_dir / entry["local_name"]
            if not path.exists():
                raise SystemExit(f"PINNED_FILE_MISSING {path}")
            raw = path.read_bytes()
            if len(raw) != int(entry["bytes"]):
                raise SystemExit(f"PIN_SIZE_MISMATCH {entry['local_name']}")
            if _sha256_bytes(raw) != entry["sha256"]:
                raise SystemExit(f"PIN_SHA256_MISMATCH {entry['local_name']}")
            texts[entry["local_name"]] = raw.decode("utf-8")
    return texts


# ------------------------------------------------------------- odds math ----

def american_to_implied(odds: float) -> float:
    """Raw (vig-inclusive) implied probability of an American price."""
    odds = float(odds)
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return (-odds) / ((-odds) + 100.0)


def devig_pair(odds_a: float, odds_b: float) -> tuple[float, float]:
    """No-vig probabilities for a two-sided market from recorded prices."""
    pa = american_to_implied(odds_a)
    pb = american_to_implied(odds_b)
    total = pa + pb
    return pa / total, pb / total


def american_profit_per_unit(odds: float) -> float:
    """Profit (excluding stake) of a winning 1-unit bet at an American price."""
    odds = float(odds)
    return odds / 100.0 if odds > 0 else 100.0 / (-odds)


# --------------------------------------------------------------- metrics ----

def probability_metrics(pairs, bins: int = 10) -> dict:
    """Log loss / Brier / accuracy / ECE-10 for (probability, outcome) pairs.

    Mirrors sportsedge.ufc_training.evaluate so model, market and Elo-only
    numbers are computed identically.
    """
    pairs = [(float(p), int(y)) for p, y in pairs]
    if not pairs:
        return {"n": 0, "log_loss": None, "brier": None,
                "accuracy": None, "calibration_error": None}
    ps = [min(1.0 - 1e-12, max(1e-12, p)) for p, _ in pairs]
    ys = [y for _, y in pairs]
    ll = -mean([y * log(p) + (1 - y) * log(max(1 - p, 1e-12)) for p, y in zip(ps, ys)])
    brier = mean([(p - y) ** 2 for p, y in zip(ps, ys)])
    acc = mean([1.0 if (p >= 0.5) == bool(y) else 0.0 for p, y in zip(ps, ys)])
    ce = 0.0
    for k in range(bins):
        lo, hi = k / bins, (k + 1) / bins
        idx = [i for i, p in enumerate(ps) if lo <= p < hi or (k == bins - 1 and p == 1.0)]
        if idx:
            ce += (len(idx) / len(ps)) * abs(mean([ps[i] for i in idx]) - mean([ys[i] for i in idx]))
    return {"n": len(ps), "log_loss": ll, "brier": brier,
            "accuracy": acc, "calibration_error": ce}


# ----------------------------------------------------------------- join ----

def join_key_norm(name: str) -> str:
    """Accent-folded normalized fighter name for cross-source matching."""
    folded = unicodedata.normalize("NFKD", name or "")
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return normalize_name(folded)


def _num(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_market_rows(text: str) -> dict[tuple[str, frozenset], dict]:
    """Index priced mdabbert rows by (date, unordered normalized pair)."""
    out: dict[tuple[str, frozenset], dict] = {}
    for row in csv.DictReader(io.StringIO(text)):
        r_odds, b_odds = _num(row.get("R_odds")), _num(row.get("B_odds"))
        if r_odds is None or b_odds is None:
            continue
        r_name, b_name = join_key_norm(row["R_fighter"]), join_key_norm(row["B_fighter"])
        key = (str(row["date"]), frozenset((r_name, b_name)))
        winner = row.get("Winner")
        winner_name = None
        if winner == "Red":
            winner_name = r_name
        elif winner == "Blue":
            winner_name = b_name
        out[key] = {
            "odds_by_name": {r_name: r_odds, b_name: b_odds},
            "winner_name": winner_name,
            "winner_raw": winner,
        }
    return out


def join_rows(bundle, market: dict) -> tuple[list[dict], dict]:
    """Join point-in-time training rows to recorded prices.

    A joined row is scored only when the two sources agree on the winner;
    disagreements are excluded and counted, never silently resolved.
    Draws / no-contests never become training rows in the history builder,
    so they are excluded structurally.
    """
    scored: list[dict] = []
    stats = {"training_rows": len(bundle.training_rows), "joined_priced": 0,
             "outcome_agree": 0, "outcome_disagree": 0, "unjoined": 0}
    for tr, meta in zip(bundle.training_rows, bundle.metadata):
        key = (tr.fight_date, frozenset((join_key_norm(tr.fighter_a), join_key_norm(tr.fighter_b))))
        entry = market.get(key)
        if entry is None:
            stats["unjoined"] += 1
            continue
        stats["joined_priced"] += 1
        a_name = join_key_norm(tr.fighter_a)
        winner_name = entry["winner_name"]
        if winner_name is None:
            stats["outcome_disagree"] += 1
            continue
        if (winner_name == a_name) != bool(tr.y_a_win):
            stats["outcome_disagree"] += 1
            continue
        stats["outcome_agree"] += 1
        odds_a = entry["odds_by_name"][a_name]
        odds_b = entry["odds_by_name"][join_key_norm(tr.fighter_b)]
        p_a_market, _ = devig_pair(odds_a, odds_b)
        scored.append({
            "row": tr,
            "meta": meta,
            "fighter_a_odds": odds_a,
            "fighter_b_odds": odds_b,
            "market_p_a": p_a_market,
        })
    return scored, stats


# ------------------------------------------------- section 5 PIT audit ----

def _of(value) -> tuple[int, int]:
    m = re.match(r"\s*(\d+)\s*of\s*(\d+)", value or "")
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def _elapsed_seconds(round_value, time_value, time_format) -> int | None:
    try:
        rounds_done = int(round_value)
    except (TypeError, ValueError):
        return None
    m = re.match(r"\s*(\d+):(\d{2})\s*$", str(time_value or ""))
    if not m or rounds_done < 1:
        return None
    # UFCStats round lengths are 5 minutes in every TIME FORMAT used here.
    return (rounds_done - 1) * 300 + int(m.group(1)) * 60 + int(m.group(2))


def _rebuilt_histories(events_text: str, results_text: str, stats_text: str):
    """Per-fighter chronological bout list from the per-fight record."""
    event_dates: dict[str, date] = {}
    for row in csv.DictReader(io.StringIO(events_text)):
        event = " ".join(str(row.get("EVENT") or "").split())
        raw = str(row.get("DATE") or "").strip()
        if event and raw:
            try:
                event_dates[event] = datetime.strptime(raw, "%B %d, %Y").date()
            except ValueError:
                continue
    per_bout: dict[tuple[str, str, str], list[int]] = defaultdict(lambda: [0, 0, 0, 0, 0])
    for row in csv.DictReader(io.StringIO(stats_text)):
        key = (" ".join(str(row.get("EVENT") or "").split()),
               " ".join(str(row.get("BOUT") or "").split()),
               join_key_norm(str(row.get("FIGHTER") or "")))
        sl, sa = _of(row.get("SIG.STR."))
        tl, ta = _of(row.get("TD"))
        agg = per_bout[key]
        agg[0] += sl; agg[1] += sa; agg[2] += tl; agg[3] += ta
        try:
            agg[4] += int(float(row.get("SUB.ATT") or 0))
        except ValueError:
            pass
    histories: dict[str, list[dict]] = defaultdict(list)
    for row in csv.DictReader(io.StringIO(results_text)):
        event = " ".join(str(row.get("EVENT") or "").split())
        bout = " ".join(str(row.get("BOUT") or "").split())
        day = event_dates.get(event)
        if day is None:
            continue
        m = re.match(r"(.+) vs\.? (.+)", bout)
        if not m:
            continue
        fa, fb = m.group(1).strip(), m.group(2).strip()
        outcome = str(row.get("OUTCOME") or "").strip().upper().replace(" ", "")
        elapsed = _elapsed_seconds(row.get("ROUND"), row.get("TIME"), row.get("TIME FORMAT"))
        for fighter, oc in ((fa, outcome), (fb, {"W/L": "L/W", "L/W": "W/L"}.get(outcome, outcome))):
            s = per_bout.get((event, bout, join_key_norm(fighter)), [0, 0, 0, 0, 0])
            histories[join_key_norm(fighter)].append({
                "date": day, "outcome": oc, "sig_l": s[0], "sig_a": s[1],
                "td_l": s[2], "td_a": s[3], "sub": s[4],
                "seconds": elapsed or 0,
            })
    for fighter in histories:
        histories[fighter].sort(key=lambda x: x["date"])
    return histories


def _entering(histories, fighter: str, day: date) -> dict | None:
    prior = [b for b in histories.get(fighter, []) if b["date"] < day]
    if not prior:
        return None
    n = len(prior)
    wins = sum(1 for b in prior if b["outcome"] == "W/L")
    losses = sum(1 for b in prior if b["outcome"] == "L/W")
    draws = sum(1 for b in prior if b["outcome"] in ("D/D", "DRAW/DRAW"))
    sig_l = sum(b["sig_l"] for b in prior)
    sig_a = sum(b["sig_a"] for b in prior)
    td_l = sum(b["td_l"] for b in prior)
    td_a = sum(b["td_a"] for b in prior)
    seconds = sum(b["seconds"] for b in prior)
    return {
        "n": n, "wins": wins, "losses": losses, "draws": draws,
        "sig_per_fight": sig_l / n,
        "sig_per_min": (sig_l / seconds * 60.0) if seconds > 0 else None,
        "sig_pct": (sig_l / sig_a) if sig_a > 0 else 0.0,
        "td_per_fight": td_l / n,
        "td_pct": (td_l / td_a) if td_a > 0 else 0.0,
    }


def run_pit_audit(market_text: str, events_text: str, results_text: str, stats_text: str) -> dict:
    """Design draft section 5: shipped aggregates vs rebuilt aggregates.

    Population: every market-dataset row side whose fighter has at least one
    prior bout in the per-fight record. The construction never uses shipped
    aggregates; this audit records whether they were point-in-time clean.
    """
    histories = _rebuilt_histories(events_text, results_text, stats_text)
    fighters_seen: set[str] = set()
    checks = 0
    wl_exact = 0
    wl_mismatch_examples: list[dict] = []
    sig_pct_ok = 0
    td_pct_ok = 0
    rate_class = {"per_fight": 0, "per_minute": 0, "ambiguous": 0, "neither": 0}
    for row in csv.DictReader(io.StringIO(market_text)):
        try:
            day = datetime.strptime(str(row["date"]), "%Y-%m-%d").date()
        except (ValueError, KeyError):
            continue
        for side, name_col in (("R", "R_fighter"), ("B", "B_fighter")):
            fighter = join_key_norm(row[name_col])
            rebuilt = _entering(histories, fighter, day)
            if rebuilt is None:
                continue
            fighters_seen.add(fighter)
            checks += 1
            shipped_w = _num(row.get(f"{side}_wins"))
            shipped_l = _num(row.get(f"{side}_losses"))
            shipped_d = _num(row.get(f"{side}_draw"))
            if (shipped_w, shipped_l, shipped_d) == (rebuilt["wins"], rebuilt["losses"], rebuilt["draws"]):
                wl_exact += 1
            elif len(wl_mismatch_examples) < 10:
                wl_mismatch_examples.append({
                    "fighter": row[name_col], "date": row["date"],
                    "shipped_w_l_d": [shipped_w, shipped_l, shipped_d],
                    "rebuilt_w_l_d": [rebuilt["wins"], rebuilt["losses"], rebuilt["draws"]],
                })
            shipped_sig_pct = _num(row.get(f"{side}_avg_SIG_STR_pct"))
            if shipped_sig_pct is not None and abs(shipped_sig_pct - rebuilt["sig_pct"]) <= 0.03:
                sig_pct_ok += 1
            shipped_td_pct = _num(row.get(f"{side}_avg_TD_pct"))
            if shipped_td_pct is not None and abs(shipped_td_pct - rebuilt["td_pct"]) <= 0.03:
                td_pct_ok += 1
            shipped_rate = _num(row.get(f"{side}_avg_SIG_STR_landed"))
            if shipped_rate is not None and rebuilt["n"] >= 3:
                def _close(a, b):
                    return b is not None and b > 0 and abs(a - b) / b <= 0.10
                pf = _close(shipped_rate, rebuilt["sig_per_fight"])
                pm = _close(shipped_rate, rebuilt["sig_per_min"])
                if pf and pm:
                    rate_class["ambiguous"] += 1
                elif pf:
                    rate_class["per_fight"] += 1
                elif pm:
                    rate_class["per_minute"] += 1
                else:
                    rate_class["neither"] += 1
    wl_rate = (wl_exact / checks) if checks else 0.0
    mixed_units = rate_class["per_fight"] > 0 and rate_class["per_minute"] > 0
    discarded = wl_rate < 0.99 or mixed_units
    return {
        "population_row_sides_checked": checks,
        "distinct_fighters_checked": len(fighters_seen),
        "wins_losses_draws_exact_match": wl_exact,
        "wins_losses_draws_exact_rate": wl_rate,
        "wins_losses_draws_mismatch_examples": wl_mismatch_examples,
        "sig_str_pct_within_0_03_rate": (sig_pct_ok / checks) if checks else 0.0,
        "td_pct_within_0_03_rate": (td_pct_ok / checks) if checks else 0.0,
        "avg_sig_str_landed_unit_classification": rate_class,
        "mixed_units_detected": mixed_units,
        "shipped_aggregates_verdict": (
            "DISCARDED_WHOLESALE_NOT_POINT_IN_TIME_CONSISTENT" if discarded
            else "CONSISTENT_WITH_REBUILT_POINT_IN_TIME"
        ),
        "construction_note": (
            "The construction uses rebuilt features only (sportsedge.ufc_history), "
            "so the screen proceeds on rebuilt features either way, exactly as "
            "design draft section 5 prescribes for a failed audit."
        ),
    }


# -------------------------------------------------------------- the model ----

def elo_only_artifact(fit_rows: list[TrainingRow]) -> LogisticArtifact:
    """A LogisticArtifact whose raw probability is the Elo expectation.

    Elo expectation = sigmoid(elo_diff * ln(10) / 400). The artifact
    standardizes elo_diff with the fit window's mean/scale, so the
    coefficient/intercept below reproduce that sigmoid exactly, and the
    repo's fit_platt can then calibrate it on the validation window.
    """
    diffs = [float(r.features.get("elo_diff", 0.0)) for r in fit_rows]
    mu = mean(diffs)
    var = mean([(x - mu) ** 2 for x in diffs])
    scale = max(var ** 0.5, 1e-6)
    k = log(10.0) / 400.0
    return LogisticArtifact(
        feature_names=("elo_diff",),
        coefficients=(k * scale,),
        intercept=k * mu,
        means=(mu,),
        scales=(scale,),
    )


def _slice(scored: list[dict], predicate) -> list[dict]:
    return [s for s in scored if predicate(s)]


def _metrics_block(model, elo_model, scored: list[dict]) -> dict:
    rows = [s["row"] for s in scored]
    ys = [int(s["row"].y_a_win) for s in scored]
    model_metrics = probability_metrics(
        [(model.probability(s["row"].features), int(s["row"].y_a_win)) for s in scored])
    return {
        "model": model_metrics,
        "market_recorded_price_no_vig": probability_metrics(
            [(s["market_p_a"], int(s["row"].y_a_win)) for s in scored]),
        "elo_only": probability_metrics(
            [(elo_model.probability(s["row"].features), int(s["row"].y_a_win)) for s in scored]),
        "n": len(rows),
        "y": ys,
    }


def _flat_bet_roi(model, scored: list[dict]) -> dict:
    """1 unit on the model's higher-probability side at the recorded price."""
    profit = 0.0
    wins = 0
    for s in scored:
        p_a = model.probability(s["row"].features)
        if p_a >= 0.5:
            stake_odds, won = s["fighter_a_odds"], bool(s["row"].y_a_win)
        else:
            stake_odds, won = s["fighter_b_odds"], not bool(s["row"].y_a_win)
        if won:
            profit += american_profit_per_unit(stake_odds)
            wins += 1
        else:
            profit -= 1.0
    n = len(scored)
    return {"rule": "1u flat on the model's argmax side at the recorded price",
            "n_bets": n, "wins": wins, "profit_units": profit,
            "roi": (profit / n) if n else None,
            "provenance_label": PROVENANCE_LABEL}


# ----------------------------------------------------------------- gates ----

def evaluate_gates(contract: dict, test_block: dict, debut_n: int,
                   training_age_days: int) -> dict:
    model = test_block["model"]
    market = test_block["market_recorded_price_no_vig"]
    elo = test_block["elo_only"]
    criteria = {}

    def _crit(name, required, observed, passed):
        criteria[name] = {"required": required, "observed": observed, "pass": bool(passed)}

    _crit("test_n_min", f">= {contract['holdout_n_min']}", test_block["n"],
          test_block["n"] >= int(contract["holdout_n_min"]))
    _crit("debut_slice_n_min", f">= {contract['debut_n_min']}", debut_n,
          debut_n >= int(contract["debut_n_min"]))
    _crit("calibration_error_max", f"<= {contract['calibration_error_max']}",
          model["calibration_error"],
          model["calibration_error"] is not None
          and model["calibration_error"] <= float(contract["calibration_error_max"]))
    brier_delta = None if (model["brier"] is None or market["brier"] is None) \
        else model["brier"] - market["brier"]
    _crit("brier_delta_vs_market_max", f"<= {contract['max_brier_delta_vs_market']}",
          brier_delta,
          brier_delta is not None and brier_delta <= float(contract["max_brier_delta_vs_market"]))
    ll_delta = None if (model["log_loss"] is None or market["log_loss"] is None) \
        else model["log_loss"] - market["log_loss"]
    _crit("log_loss_delta_vs_market_max", f"<= {contract['max_log_loss_delta_vs_market']}",
          ll_delta,
          ll_delta is not None and ll_delta <= float(contract["max_log_loss_delta_vs_market"]))
    _crit("log_loss_strictly_better_than_elo_only", "model log loss < Elo-only log loss",
          {"model": model["log_loss"], "elo_only": elo["log_loss"]},
          model["log_loss"] is not None and elo["log_loss"] is not None
          and model["log_loss"] < elo["log_loss"])
    passed = all(c["pass"] for c in criteria.values())
    return {
        "criteria": criteria,
        "screen_verdict": "SCREEN_PASSED" if passed else "FAILED_SCREEN",
        "promotion_note": (
            "SCREEN_PASSED means the draft's Leg 1 screen passed (ARMED). It is "
            "not a promotion: promotion remains a separate act and Leg 2 (the "
            "forward DraftKings leg) is still required."
        ),
        "contract_terms_reported_not_gated_here": {
            "training_data_max_age_days": {
                "contract_max": int(contract["training_data_max_age_days"]),
                "observed_gap_days_newest_calibration_bout_to_test_start": training_age_days,
                "reading": "Within the limit under the Leg 1 reading; the term binds the forward promotion act (Leg 2) in the draft.",
            },
            "closing_market_provenance_required": {
                "contract_value": bool(contract["closing_market_provenance_required"]),
                "reading": "Leg 1 is scored against RECORDED_PRICE_NOT_DK_CLOSE by the design's own section 3/6 terms; genuine closing-market provenance remains required for Leg 2 / promotion.",
            },
            "short_notice_slice_required": {
                "contract_value": bool(contract["short_notice_slice_required"]),
                "reading": "Neither pinned source records booking changes, so the short-notice slice is NOT_IDENTIFIABLE historically; reported here as required and not gated, per draft section 6 Leg 1.",
                "slice_status": "NOT_IDENTIFIABLE_FROM_PINNED_SOURCES",
            },
        },
    }


# ------------------------------------------------------------------- main ----

def run_screen(data_dir: Path, pins_path: Path, contract_path: Path) -> dict:
    pins = json.loads(pins_path.read_text(encoding="utf-8"))
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    texts = load_pinned_files(data_dir, pins)

    audit = run_pit_audit(
        texts["ufc-master.csv"],
        texts["ufc_event_details.csv"],
        texts["ufc_fight_results.csv"],
        texts["ufc_fight_stats.csv"],
    )

    bundle = build_history_from_text(
        events_text=texts["ufc_event_details.csv"],
        results_text=texts["ufc_fight_results.csv"],
        stats_text=texts["ufc_fight_stats.csv"],
        fighters_text=texts["ufc_fighter_tott.csv"],
        min_date="2010-01-01",
    )
    market = load_market_rows(texts["ufc-master.csv"])
    scored, join_stats = join_rows(bundle, market)

    fit_rows = [s["row"] for s in scored if s["row"].fight_date <= FIT_END]
    cal = [s for s in scored if CAL_START <= s["row"].fight_date <= CAL_END]
    test = [s for s in scored if TEST_START <= s["row"].fight_date <= TEST_END]
    cal_rows = [s["row"] for s in cal]

    model = fit_logistic(fit_rows)
    model = fit_platt(model, cal_rows)
    elo_model = fit_platt(elo_only_artifact(fit_rows), cal_rows)

    test_block = _metrics_block(model, elo_model, test)
    # Cross-check the local metric implementation against the repo evaluator.
    repo_eval = evaluate(model, [s["row"] for s in test])
    assert abs(repo_eval.log_loss - test_block["model"]["log_loss"]) < 1e-9
    assert abs(repo_eval.brier - test_block["model"]["brier"]) < 1e-9
    assert abs(repo_eval.calibration_error - test_block["model"]["calibration_error"]) < 1e-9

    debut = _slice(test, lambda s: min(int(s["meta"]["fighter_a_experience"]),
                                       int(s["meta"]["fighter_b_experience"])) == 0)
    slices = {
        "all_test": {k: v for k, v in test_block.items() if k != "y"},
        "ufc_debut_any": {k: v for k, v in _metrics_block(model, elo_model, debut).items() if k != "y"},
        "male": {k: v for k, v in _metrics_block(model, elo_model, _slice(test, lambda s: s["meta"]["gender"] == "MALE")).items() if k != "y"},
        "female": {k: v for k, v in _metrics_block(model, elo_model, _slice(test, lambda s: s["meta"]["gender"] == "FEMALE")).items() if k != "y"},
        "three_round": {k: v for k, v in _metrics_block(model, elo_model, _slice(test, lambda s: int(s["meta"]["scheduled_rounds"]) == 3)).items() if k != "y"},
        "five_round": {k: v for k, v in _metrics_block(model, elo_model, _slice(test, lambda s: int(s["meta"]["scheduled_rounds"]) == 5)).items() if k != "y"},
    }
    weight_classes = sorted({str(s["meta"]["weight_class"]) for s in test if s["meta"]["weight_class"]})
    slices["weight_class"] = {
        wc: {k: v for k, v in _metrics_block(
            model, elo_model, _slice(test, lambda s, w=wc: s["meta"]["weight_class"] == w)).items() if k != "y"}
        for wc in weight_classes
    }

    roi = _flat_bet_roi(model, test)
    newest_cal = max(s["row"].fight_date for s in cal)
    training_age_days = (date.fromisoformat(TEST_START) - date.fromisoformat(newest_cal)).days
    gates = evaluate_gates(contract, test_block, len(debut), training_age_days)

    return {
        "schema_version": 1,
        "family": "UFC / MONEYLINE_H2H",
        "construction": "UFC_ML_PIT_RATING_V1 (existing engine: sportsedge.ufc_training logistic over FEATURES; features rebuilt point-in-time by sportsedge.ufc_history)",
        "provenance_label": PROVENANCE_LABEL,
        "pins_file": "PINS.json",
        "protocol": {
            "fit_window": f"<= {FIT_END}",
            "calibration_window": f"{CAL_START}..{CAL_END} (Platt only)",
            "test_window": f"{TEST_START}..{TEST_END}",
            "features": "sportsedge.ufc_training.FEATURES",
            "learner": "sportsedge.ufc_training.fit_logistic (defaults) + fit_platt (defaults)",
            "market_baseline": "mdabbert recorded prices, de-vigged, RECORDED_PRICE_NOT_DK_CLOSE",
            "reference_baseline": "Elo-only logistic artifact (Elo expectation), Platt-calibrated on the same validation window",
        },
        "join": join_stats,
        "window_counts": {"fit": len(fit_rows), "calibration": len(cal_rows), "test": len(test)},
        "pit_audit_section5": audit,
        "slices": slices,
        "flat_bet_roi_test": roi,
        "gates": gates,
    }


def main() -> None:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--pins", default=str(here / "PINS.json"))
    ap.add_argument("--contract", default="config/ufc_promotion_contract_v1.json")
    ap.add_argument("--out", default=str(here / "screen_results.json"))
    args = ap.parse_args()
    result = run_screen(Path(args.data_dir), Path(args.pins), Path(args.contract))
    Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "verdict": result["gates"]["screen_verdict"],
        "test_n": result["window_counts"]["test"],
        "model": result["slices"]["all_test"]["model"],
        "market": result["slices"]["all_test"]["market_recorded_price_no_vig"],
        "elo_only": result["slices"]["all_test"]["elo_only"],
        "roi": result["flat_bet_roi_test"]["roi"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
