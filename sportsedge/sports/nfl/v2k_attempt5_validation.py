"""NFL V2K Attempt-5 market-calibration development validation."""
from __future__ import annotations

from pathlib import Path
from typing import Mapping

from . import v2k_attempt1_validation as a1
from .v2k_attempt5_market_calibration import (
    FAIR_SPREAD_SCALE,
    FAIR_TOTAL_SCALE,
    build_calibration_rows,
    choose_parameters,
    evaluate_fold,
    calibration,
)

NFL = Path(__file__).resolve().parent
ROOT = NFL.parents[2]
CONTRACT_PATH = NFL / "NFL_V2K_DEVELOPMENT_VALIDATION_PREATTEMPT_V5.json"
EXPOSURE_PATH = NFL / "NFL_V2K_DEVELOPMENT_EXPOSURE_V4.json"
RESULT_SCHEMA = "NFL_V2K_ATTEMPT5_DEVELOPMENT_VALIDATION_V1"


def _load_json(path: Path) -> dict:
    return a1._load_json(path)


def preflight() -> dict:
    contract = _load_json(CONTRACT_PATH)
    exposure = _load_json(EXPOSURE_PATH)
    problems = []
    if contract.get("status") != "FROZEN_ATTEMPT5_READY_FOR_DEVELOPMENT_VALIDATION":
        problems.append("V2K_ATTEMPT5_NOT_FROZEN_READY")
    if exposure.get("development_budget_units_used") != 4:
        problems.append("V2K_ATTEMPT5_EXPOSURE_COUNT_INVALID")
    if exposure.get("development_budget_units_remaining") != 1:
        problems.append("V2K_ATTEMPT5_REMAINING_BUDGET_INVALID")
    if any(bool(v) for v in (exposure.get("authority") or {}).values()):
        problems.append("V2K_ATTEMPT5_EXPOSURE_AUTHORITY_ESCALATION")
    ident = contract.get("implementation_identity") or {}
    if ident.get("status") != "FROZEN":
        problems.append("V2K_ATTEMPT5_CODE_IDENTITY_NOT_FROZEN")
    for path_key, sha_key in (
        ("core_path", "core_git_blob_sha1"),
        ("validation_path", "validation_git_blob_sha1"),
        ("runner_path", "runner_git_blob_sha1"),
    ):
        rel = ident.get(path_key)
        want = ident.get(sha_key)
        if not rel or not want:
            problems.append("V2K_ATTEMPT5_IMPLEMENTATION_IDENTITY_INCOMPLETE")
        elif a1.git_blob_sha1(ROOT / rel) != want:
            problems.append("V2K_ATTEMPT5_CODE_IDENTITY_DRIFT:" + str(rel))
    if problems:
        raise SystemExit("PREFLIGHT_FAILED:" + ";".join(problems))
    return contract


def evaluate(schedule: Mapping[str, Mapping], contract: Mapping) -> dict:
    rows = build_calibration_rows(schedule)
    test_seasons = [int(x) for x in contract["fold_plan"]["test_seasons"]]
    fold_rows = []
    calibration_rows = {"spread": [], "total": []}
    for market in ("spread", "total"):
        for season in test_seasons:
            fold = evaluate_fold(rows, test_season=season, market=market)
            calibration_rows[market].extend(fold.pop("rows"))
            fold_rows.append(fold)

    predictive = {}
    gate = contract["acceptance"]["predictive"]
    for market in ("spread", "total"):
        folds = [f for f in fold_rows if f["market"] == market]
        wins = sum(int(f["candidate_beats_baseline"]) for f in folds)
        total = len(folds)
        n = sum(int(f["n"]) for f in folds)
        baseline_ll = sum(float(f["baseline_log_loss"]) * int(f["n"]) for f in folds) / n
        candidate_ll = sum(float(f["candidate_log_loss"]) * int(f["n"]) for f in folds) / n
        cal = calibration(calibration_rows[market])
        fold_pass = bool(total and wins / total >= float(gate["minimum_fold_win_rate"]))
        overall_pass = candidate_ll < baseline_ll
        cal_pass = (
            cal["max_bin_deviation"] is not None
            and cal["max_bin_deviation"] <= float(gate["calibration_max_nonempty_bin_deviation"])
        )
        predictive[market] = {
            "fold_wins": wins,
            "fold_total": total,
            "fold_win_rate": wins / total if total else 0.0,
            "required_fold_win_rate": float(gate["minimum_fold_win_rate"]),
            "fold_win_pass": fold_pass,
            "overall_n": n,
            "baseline_log_loss": baseline_ll,
            "candidate_log_loss": candidate_ll,
            "overall_log_loss_pass": overall_pass,
            "calibration": cal,
            "calibration_pass": cal_pass,
            "pass": fold_pass and overall_pass and cal_pass,
        }

    overall = all(v["pass"] for v in predictive.values())
    spread_intercept, spread_line_beta = choose_parameters(rows, market="spread")
    total_intercept, total_line_beta = choose_parameters(rows, market="total")
    live_parameters = {
        "spread_intercept": spread_intercept,
        "spread_line_beta": spread_line_beta,
        "total_intercept": total_intercept,
        "total_line_beta": total_line_beta,
        "fair_spread_scale": FAIR_SPREAD_SCALE,
        "fair_total_scale": FAIR_TOTAL_SCALE,
        "fair_center_formula": "line + fair_scale*logit(calibrated_market_probability)",
        "fit_scope": "ALL_FROZEN_2016_2025_ROWS_AFTER_ATTEMPT5_DECISION_RULES_FIXED",
    }
    return {
        "schema": RESULT_SCHEMA,
        "candidate_family": contract["candidate_family"],
        "verdict": "ATTEMPT5_PASS" if overall else "ATTEMPT5_FAIL",
        "predictive_gate": predictive,
        "folds": fold_rows,
        "live_parameters": live_parameters,
        "evaluated_row_count": len(rows),
        "sportsbook_prices_consumed_in_fit": True,
        "market_role": "TWO_WAY_NO_VIG_BASELINE_PLUS_TRAINING_ONLY_LINE_CALIBRATION",
        "attempt_consumed": True,
        "development_budget_exhausted_after_run": True,
        "authority": {
            "model_p": False, "pricing": False, "promotion": False, "staking": False,
            "production_release": False, "official": False, "untouched_readout": False,
        },
    }


__all__ = ["evaluate", "preflight", "RESULT_SCHEMA"]
