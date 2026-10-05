"""NFL V2K Attempt-4 market-anchored residual development validation."""
from __future__ import annotations

from pathlib import Path
from typing import Mapping

from . import v2k_attempt1_validation as a1
from .v2k_attempt4_market_residual import build_residual_rows, evaluate_fold, calibration

NFL = Path(__file__).resolve().parent
ROOT = NFL.parents[2]
CONTRACT_PATH = NFL / "NFL_V2K_DEVELOPMENT_VALIDATION_PREATTEMPT_V4.json"
EXPOSURE_PATH = NFL / "NFL_V2K_DEVELOPMENT_EXPOSURE_V3.json"
RESULT_SCHEMA = "NFL_V2K_ATTEMPT4_DEVELOPMENT_VALIDATION_V1"


def _load_json(path: Path) -> dict:
    return a1._load_json(path)


def preflight() -> dict:
    contract = _load_json(CONTRACT_PATH)
    exposure = _load_json(EXPOSURE_PATH)
    problems = []
    if contract.get("status") != "FROZEN_ATTEMPT4_READY_FOR_DEVELOPMENT_VALIDATION":
        problems.append("V2K_ATTEMPT4_NOT_FROZEN_READY")
    if exposure.get("development_budget_units_used") != 3:
        problems.append("V2K_ATTEMPT4_EXPOSURE_COUNT_INVALID")
    if exposure.get("development_budget_units_remaining") != 2:
        problems.append("V2K_ATTEMPT4_REMAINING_BUDGET_INVALID")
    if any(bool(v) for v in (exposure.get("authority") or {}).values()):
        problems.append("V2K_ATTEMPT4_EXPOSURE_AUTHORITY_ESCALATION")
    ident = contract.get("implementation_identity") or {}
    if ident.get("status") != "FROZEN":
        problems.append("V2K_ATTEMPT4_CODE_IDENTITY_NOT_FROZEN")
    for path_key, sha_key in (
        ("core_path", "core_git_blob_sha1"),
        ("validation_path", "validation_git_blob_sha1"),
        ("runner_path", "runner_git_blob_sha1"),
    ):
        rel = ident.get(path_key)
        want = ident.get(sha_key)
        if not rel or not want:
            problems.append("V2K_ATTEMPT4_IMPLEMENTATION_IDENTITY_INCOMPLETE")
        elif a1.git_blob_sha1(ROOT / rel) != want:
            problems.append("V2K_ATTEMPT4_CODE_IDENTITY_DRIFT:" + str(rel))
    if problems:
        raise SystemExit("PREFLIGHT_FAILED:" + ";".join(problems))
    return contract


def evaluate(schedule: Mapping[str, Mapping], contract: Mapping) -> dict:
    rows = build_residual_rows(schedule)
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
    return {
        "schema": RESULT_SCHEMA,
        "candidate_family": contract["candidate_family"],
        "verdict": "ATTEMPT4_PASS" if overall else "ATTEMPT4_FAIL",
        "predictive_gate": predictive,
        "folds": fold_rows,
        "evaluated_row_count": len(rows),
        "sportsbook_prices_consumed_in_fit": True,
        "market_role": "BASELINE_ANCHOR_PLUS_STRICTLY_PRIOR_TEAM_RESIDUAL",
        "attempt_consumed": True,
        "authority": {
            "model_p": False,
            "pricing": False,
            "promotion": False,
            "staking": False,
            "production_release": False,
            "official": False,
            "untouched_readout": False,
        },
    }


__all__ = ["evaluate", "preflight", "RESULT_SCHEMA"]
