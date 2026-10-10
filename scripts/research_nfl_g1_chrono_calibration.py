#!/usr/bin/env python3
"""Research-only chronological NFL G1 moneyline intercept calibration.

Consumes historical, season-labelled out-of-fold home-win probabilities from the
unchanged G1 distribution path. No production model, odds, staking or card authority.
Train-season observations alone determine the intercept; later seasons are held out.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from math import exp, isfinite, log
from pathlib import Path

SCHEMA = "NFL_G1_CHRONO_INTERCEPT_RESEARCH_V1"
MODEL = "NFL_LOCATION_SYMMETRIC_RIDGE_G1"


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = exp(-x)
        return 1.0 / (1.0 + z)
    z = exp(x)
    return z / (1.0 + z)


def _adjust(p: float, intercept: float) -> float:
    return _sigmoid(log(p / (1.0 - p)) + intercept)


def _parse(rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError("NFL_G1_CALIBRATION_ROWS_REQUIRED")
    seen = set()
    parsed = []
    for row in rows:
        if not isinstance(row, dict) or row.get("model_family") != MODEL:
            raise ValueError("NFL_G1_CALIBRATION_MODEL_IDENTITY_INVALID")
        if row.get("evidence_role") != "RECONSTRUCTED_DEVELOPMENT":
            raise ValueError("NFL_G1_CALIBRATION_EVIDENCE_ROLE_INVALID")
        season, gid = row.get("season"), row.get("game_id")
        if type(season) is not int or not 2018 <= season <= 2035 or not isinstance(gid, str) or not gid.strip():
            raise ValueError("NFL_G1_CALIBRATION_GAME_IDENTITY_INVALID")
        if (season, gid) in seen:
            raise ValueError("NFL_G1_CALIBRATION_DUPLICATE_GAME")
        seen.add((season, gid))
        p = row.get("moneyline_home_p")
        if type(p) not in (float, int) or not isfinite(p) or not 0 < p < 1:
            raise ValueError("NFL_G1_CALIBRATION_PROBABILITY_INVALID")
        outcome = row.get("home_win")
        if type(outcome) not in (bool, int) or outcome not in (0, 1):
            raise ValueError("NFL_G1_CALIBRATION_BINARY_RESULT_REQUIRED")
        parsed.append((season, gid, float(p), int(outcome)))
    return parsed


def _metrics(rows, intercept):
    eps = 1e-15
    n = len(rows)
    ps = [_adjust(p, intercept) for _, _, p, _ in rows]
    brier = sum((p - y) ** 2 for p, (_, _, _, y) in zip(ps, rows)) / n
    ll = -sum(y * log(max(eps, min(1-eps, p))) + (1-y) * log(max(eps, min(1-eps, 1-p)))
              for p, (_, _, _, y) in zip(ps, rows)) / n
    return {"n": n, "brier": brier, "log_loss": ll,
            "mean_predicted": sum(ps) / n,
            "observed_home_win_rate": sum(r[3] for r in rows) / n}


def evaluate(rows, *, train_through=2023, holdout_from=2024, min_train=200, min_holdout=100):
    if type(train_through) is not int or type(holdout_from) is not int or train_through >= holdout_from:
        raise ValueError("NFL_G1_CALIBRATION_CHRONOLOGY_INVALID")
    parsed = _parse(rows)
    train = [r for r in parsed if r[0] <= train_through]
    test = [r for r in parsed if r[0] >= holdout_from]
    if len(train) < min_train or len(test) < min_holdout:
        raise ValueError("NFL_G1_CALIBRATION_HOLDOUT_UNDERSIZED")
    observed = sum(r[3] for r in train) / len(train)
    if not 0 < observed < 1:
        raise ValueError("NFL_G1_CALIBRATION_TRAIN_SINGLE_CLASS")
    # Prespecified one-parameter calibration-in-the-large, no sportsbook input.
    # Monotone bisection avoids dependency on a stochastic optimizer.
    lo, hi = -20.0, 20.0
    for _ in range(90):
        mid = (lo + hi) / 2
        mean_p = sum(_adjust(r[2], mid) for r in train) / len(train)
        if mean_p < observed:
            lo = mid
        else:
            hi = mid
    offset = (lo + hi) / 2
    return {"schema": SCHEMA, "model_family": MODEL,
            "train_through": train_through, "holdout_from": holdout_from,
            "train_n": len(train), "holdout_n": len(test),
            "train_fitted_intercept": offset,
            "train_baseline": _metrics(train, 0.0),
            "train_adjusted": _metrics(train, offset),
            "holdout_baseline": _metrics(test, 0.0),
            "holdout_adjusted": _metrics(test, offset),
            "holdout_by_season": {
                str(s): {"baseline": _metrics([r for r in test if r[0] == s], 0.0),
                         "adjusted": _metrics([r for r in test if r[0] == s], offset)}
                for s in sorted({r[0] for r in test})},
            "evidence_class": "REUSED_HISTORICAL_RESEARCH_ONLY",
            "market_prices_used_for_fit": False,
            "production_model_modified": False,
            "positive_ev_proven": False,
            "staking_authority": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--train-through", type=int, default=2023)
    parser.add_argument("--holdout-from", type=int, default=2024)
    args = parser.parse_args(argv)
    raw = args.input.read_bytes()
    result = evaluate(json.loads(raw), train_through=args.train_through,
                      holdout_from=args.holdout_from)
    result["input_sha256"] = hashlib.sha256(raw).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "train_n": result["train_n"],
                      "holdout_n": result["holdout_n"], "staking_authority": False}))


if __name__ == "__main__":
    main()
