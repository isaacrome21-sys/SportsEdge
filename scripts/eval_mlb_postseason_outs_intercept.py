#!/usr/bin/env python3
"""2024/2025 time-held-out postseason pitcher-outs recalibration experiment.

Train a SINGLE shared log-odds offset on strictly earlier postseason seasons:
2023 -> 2024, then 2023+2024 -> 2025. The score probabilities are the
point-in-time historical regular-season marginal from the merged 2023-25
official boxscore audit, with and without a capped disjoint older-20 prior.

This post-season intercept is research ONLY; it is NOT a fitted early-hook
mechanism or a deployable workload distribution. No odds or target-year
results enter the fit. Correlated threshold rows are game-clustered for
uncertainty. No live pitcher pricing changes.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from math import exp, isfinite, log
from pathlib import Path
from random import Random
from statistics import mean
from typing import Any, Mapping, Sequence

SOURCE_VERSION = "mlb_postseason_starter_workload_audit_2023_2025_v1"
VERSION = "mlb_postseason_outs_intercept_temporal_holdout_v1"
FOLDS = ((2024, (2023,)), (2025, (2023, 2024)))
INPUT_KEYS = ("p_recent_only", "p_recent_plus_capped_prior")
LINE_GRID = (12.5, 15.5, 17.5)
CLUSTER_BOOTSTRAP_DRAWS = 2000


def _clamp_p(p: float) -> float:
    p = float(p)
    if not isfinite(p) or p < 0 or p > 1:
        raise ValueError("Expected valid research probability")
    return min(1 - 1e-9, max(1e-9, p))


def _logit(p: float) -> float:
    x = _clamp_p(p)
    return log(x / (1 - x))


def adjusted_probability(p: float, intercept: float) -> float:
    if not isfinite(intercept) or abs(intercept) > 6.01:
        raise ValueError("Invalid independent postseason intercept")
    x = _logit(p) + intercept
    return 1 / (1 + exp(-x))


def fit_intercept(records: Sequence[Mapping[str, Any]], source: str) -> float:
    """Solve predeclared one-parameter Bernoulli score equation on training only."""
    if source not in INPUT_KEYS:
        raise ValueError("Unrecognized historical model probability source")
    if len(records) < 100:
        raise ValueError("Insufficient historical training threshold rows")
    probs = [_logit(r[source]) for r in records]
    outcomes = [float(r["actual_over"]) for r in records]
    if any(y not in (0.0, 1.0) for y in outcomes):
        raise ValueError("Nonbinary historical starter settlement")
    lo, hi = -6.0, 6.0
    for _ in range(80):
        mid = (lo + hi) / 2
        net = sum(1 / (1 + exp(-(p + mid))) - y for p, y in zip(probs, outcomes))
        if net > 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def loss(records: Sequence[Mapping[str, Any]], source: str, offset: float = 0) -> dict[str, float]:
    if not records:
        raise ValueError("Missing holdout records")
    probs = [adjusted_probability(r[source], offset) for r in records]
    ys = [float(r["actual_over"]) for r in records]
    return {
        "brier": mean((p - y) ** 2 for p, y in zip(probs, ys)),
        "log_loss": mean(-y * log(p) - (1 - y) * log(1 - p) for p, y in zip(probs, ys)),
        "actual_rate": mean(ys),
        "predicted_rate": mean(probs),
    }


def starter_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    if payload.get("version") != SOURCE_VERSION or tuple(payload.get("frozen_seasons") or []) != (2023, 2024, 2025):
        raise ValueError("Wrong official postseason boxscore audit contract")
    starts = payload.get("starts")
    if not isinstance(starts, list) or not starts:
        raise ValueError("Missing official postseason starts")
    rows, observed = [], set()
    for starter in starts:
        if starter.get("history_status") != "EVALUATED":
            continue
        game_pk, pid = int(starter["game_pk"]), int(starter["player_id"])
        season = int(str(starter["date"])[:4])
        matches = [r for r in starter.get("records") or [] if r.get("market") == "PITCHER_OUTS"]
        if len(matches) != len(LINE_GRID) or {float(r["line"]) for r in matches} != set(LINE_GRID):
            raise ValueError("Incomplete predeclared pitcher-outs threshold grid")
        for row in matches:
            if int(row["game_pk"]) != game_pk or int(row["pitcher_id"]) != pid:
                raise ValueError("Mismatched historical game/pitcher evidence")
            if int(str(row["date"])[:4]) != season:
                raise ValueError("Inconsistent year in evaluation row")
            key = (game_pk, pid, float(row["line"]))
            if key in observed:
                raise ValueError("Duplicate pitcher-game threshold")
            observed.add(key)
            y=float(row["actual_over"])
            if y not in (0, 1):
                raise ValueError("Unsettled postseason outs outcome")
            for src in INPUT_KEYS:
                _clamp_p(float(row[src]))
            rows.append(dict(row, year=season))
    if len(rows) < 100:
        raise ValueError("Insufficient evaluable postseason outs threshold history")
    return rows


def game_cluster_bootstrap(rows: Sequence[Mapping[str, Any]], *, source: str,
                           intercept: float, seed: int) -> list[float]:
    """Descriptive bootstrap of adjusted minus unadjusted Brier, at game level."""
    groups: dict[int, list[float]] = defaultdict(list)
    for r in rows:
        y=float(r["actual_over"])
        p0=adjusted_probability(float(r[source]), 0)
        p1=adjusted_probability(float(r[source]), intercept)
        groups[int(r["game_pk"])].append((p1-y)**2-(p0-y)**2)
    vals=[mean(v) for _,v in sorted(groups.items())]
    if len(vals) < 20:
        raise ValueError("Too few independent game clusters")
    rng=Random(seed)
    boots=sorted(mean(vals[rng.randrange(len(vals))] for _ in vals)
                 for _ in range(CLUSTER_BOOTSTRAP_DRAWS))
    return [boots[int(0.025*len(boots))], boots[int(0.975*len(boots))]]


def evaluate(payload: Mapping[str, Any]) -> dict[str, Any]:
    rows=starter_rows(payload)
    reports=[]
    for year, train_years in FOLDS:
        if not train_years or max(train_years) >= year:
            raise ValueError("Postseason target-year leakage")
        train=[r for r in rows if r["year"] in train_years]
        holdout=[r for r in rows if r["year"] == year]
        if len(holdout) < 100:
            raise ValueError(f"Insufficient postseason holdout for {year}")
        if len({r["game_pk"] for r in holdout}) < 25:
            raise ValueError(f"Insufficient independent game clusters in {year}")
        options={}
        for source in INPUT_KEYS:
            offset=fit_intercept(train,source)
            base=loss(holdout,source)
            candidate=loss(holdout,source,offset)
            options[source]={
                "trained_on_years":list(train_years),
                "evaluated_on_year":year,
                "train_rows":len(train),
                "holdout_rows":len(holdout),
                "fit_intercept_log_odds":offset,
                "unadjusted":base,
                "postseason_adjusted":candidate,
                "brier_delta":candidate["brier"]-base["brier"],
                "log_loss_delta":candidate["log_loss"]-base["log_loss"],
                "paired_game_cluster_bootstrap_95_brier_delta":game_cluster_bootstrap(
                    holdout,source=source,intercept=offset,seed=year*100),
            }
        reports.append({
            "heldout_year":year,
            "training_years":list(train_years),
            "heldout_pitcher_appearances":len(holdout)//len(LINE_GRID),
            "heldout_independent_games":len({r["game_pk"] for r in holdout}),
            "models":options,
        })
    return {
        "version":VERSION,
        "source_version":SOURCE_VERSION,
        "frozen_train_holdout_folds":[{"target":yr,"training":list(ts)} for yr,ts in FOLDS],
        "research_only":True,
        "production_probabilities_changed":False,
        "deployable_workload_calibration":False,
        "postseason_pitcher_prop_cards_allowed":False,
        "market_prices_used":False,
        "training_2025_outcomes_into_2025_model":False,
        "evaluation_unit":"actual postseason starter/threshold, with descriptive GAME-level paired bootstrap",
        "limitations":"2 chronological historical holdout seasons, 3 correlated half-lines per starter, no opponent/lineup/manager hooks modeled, no prospective/post-2025 calibration",
        "reports":reports,
    }


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument("--input",required=True)
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    payload=evaluate(json.loads(Path(args.input).read_text(encoding="utf-8")))
    out=Path(args.output)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    for fold in payload["reports"]:
        for src,r in fold["models"].items():
            print(f"POSTSEASON_OUTS_HOLDOUT {fold['heldout_year']} {src} "
                  f"offset={r['fit_intercept_log_odds']:+.5f} "
                  f"brier={r['unadjusted']['brier']:.5f}->{r['postseason_adjusted']['brier']:.5f} "
                  f"logloss={r['unadjusted']['log_loss']:.5f}->{r['postseason_adjusted']['log_loss']:.5f}")
    print("NO_LIVE_PITCHER_PROP_PROMOTION")


if __name__ == "__main__":
    main()
