#!/usr/bin/env python3
"""Reproduce the frozen NFL baseline and attempt-one opponent adjustment.

This wrapper does not define a new candidate. It calls the already-evaluated
feature implementations with the training / holdout window owned by the frozen
NFL feature-search policy and writes a side-by-side research artifact.
Reproducing attempt one does not consume another feature-search attempt.
"""
from __future__ import annotations

import importlib.util
import json
from collections import defaultdict
from itertools import groupby
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FIT_PATH = ROOT / "scripts" / "fit_football_baselines.py"
POLICY_PATH = ROOT / "config" / "research" / "nfl_feature_search_policy_2026-09-10.json"


def load_policy():
    if not POLICY_PATH.exists():
        raise RuntimeError("NFL_FEATURE_SEARCH_POLICY_MISSING")
    try:
        policy = json.loads(POLICY_PATH.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("NFL_FEATURE_SEARCH_POLICY_UNREADABLE") from exc

    if policy.get("schema") != "NFL_FEATURE_SEARCH_POLICY_V2":
        raise RuntimeError("NFL_FEATURE_SEARCH_POLICY_SCHEMA_MISMATCH")
    if policy.get("status") != "FROZEN_BEFORE_FEATURE_EVALUATION":
        raise RuntimeError("NFL_FEATURE_SEARCH_POLICY_NOT_FROZEN")

    training = tuple(policy.get("training_seasons", ()))
    holdout = policy.get("holdout_season")
    if not training or not all(isinstance(season, int) for season in training):
        raise RuntimeError("NFL_FEATURE_SEARCH_POLICY_TRAINING_INVALID")
    if not isinstance(holdout, int):
        raise RuntimeError("NFL_FEATURE_SEARCH_POLICY_HOLDOUT_INVALID")
    if tuple(sorted(set(training))) != training:
        raise RuntimeError("NFL_FEATURE_SEARCH_POLICY_TRAINING_NOT_STRICTLY_ORDERED")
    if max(training) >= holdout:
        raise RuntimeError("NFL_FEATURE_SEARCH_POLICY_WINDOW_OVERLAP")

    return policy, training, holdout


def load_fitter():
    spec = importlib.util.spec_from_file_location("fit_football_baselines", FIT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("NFL_ATTEMPT1_FITTER_IMPORT_FAILED")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def align_market_rows(games):
    usable = sorted(games, key=lambda z: (z["date"], z["id"]))
    keys = []
    prior = defaultdict(int)
    for d, grp in groupby(usable, key=lambda z: z["date"]):
        batch = list(grp)
        for g in batch:
            if prior[g["home"]] >= 5 and prior[g["away"]] >= 5:
                keys.append(g)
        for g in batch:
            prior[g["home"]] += 1
            prior[g["away"]] += 1
    return keys


def market_benchmark(keyed, actual_margin, holdout):
    is_hold = np.array([g["date"].startswith(str(holdout)) for g in keyed])
    spread = np.array([
        g["spread_line"] if g.get("spread_line") is not None else np.nan
        for g in keyed
    ], dtype=float)
    ok = is_hold & np.isfinite(spread)
    actual = actual_margin[ok]
    estimate = spread[ok]
    corr = float(np.corrcoef(estimate, actual)[0, 1])
    if not np.isfinite(corr) or corr <= 0:
        raise RuntimeError(f"NFL_SPREAD_SIGN_NOT_VERIFIED:{corr}")
    return {
        "n_holdout": int(ok.sum()),
        "rmse": float(np.sqrt(np.mean((estimate - actual) ** 2))),
        "spread_line_home_margin_correlation": corr,
        "source_field": "spread_line",
    }


def evaluate_feature_set(mod, games, feature_set, holdout):
    x, ym, _yt, names, dates = mod.features(games, feature_set)
    mod.hold_dates = dates
    mod.feature_names = names
    result = mod.run_target(x, ym, holdout)
    return result, ym


def main():
    policy, training, holdout = load_policy()
    seasons = set(training + (holdout,))
    mod = load_fitter()
    games, source_sha, source = mod.nfl(seasons)
    games = [
        g for g in games
        if g["date"][:4].isdigit() and int(g["date"][:4]) <= holdout
    ]
    keyed = align_market_rows(games)

    baseline, baseline_ym = evaluate_feature_set(mod, games, "baseline", holdout)
    attempt1, attempt_ym = evaluate_feature_set(mod, games, "opponent_strength", holdout)
    if len(baseline_ym) != len(attempt_ym):
        raise RuntimeError("NFL_ATTEMPT1_ROW_ALIGNMENT_MISMATCH")
    market = market_benchmark(keyed, attempt_ym, holdout)

    base_rmse = float(baseline["holdout"]["rmse"])
    cand_rmse = float(attempt1["holdout"]["rmse"])
    close_rmse = float(market["rmse"])
    artifact = {
        "schema": "NFL_FEATURE_SEARCH_ATTEMPT_COMPARISON_V1",
        "status": "RESEARCH_ONLY_NOT_MODEL_P",
        "attempt_number": 1,
        "candidate_family": "opponent_adjustment",
        "candidate_feature_set": "opponent_strength",
        "training_seasons": list(training),
        "holdout_season": holdout,
        "policy_path": str(POLICY_PATH.relative_to(ROOT)),
        "policy_schema": policy["schema"],
        "source": source,
        "source_sha256": source_sha,
        "baseline": baseline,
        "candidate": attempt1,
        "closing_spread": market,
        "comparison": {
            "candidate_minus_baseline_rmse": cand_rmse - base_rmse,
            "candidate_minus_closing_rmse": cand_rmse - close_rmse,
            "baseline_minus_closing_rmse": base_rmse - close_rmse,
            "candidate_beats_baseline": cand_rmse < base_rmse,
            "candidate_beats_closing_spread": cand_rmse < close_rmse,
            "verdict": "BEATS_CLOSING_LINE" if cand_rmse < close_rmse else "WORSE_THAN_CLOSING_LINE",
        },
        "governance": {
            "attempts_consumed_after_this_result": 1,
            "promotion_changed": False,
            "eligibility_changed": False,
            "model_p_created": False,
            "official_bet_authorized": False,
        },
    }
    out = ROOT / "artifacts" / "research" / "nfl_feature_attempt1_comparison.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2) + "\n")
    print(json.dumps(artifact, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
