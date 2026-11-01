#!/usr/bin/env python3
"""Prospective-method historical CFB moneyline residual study; no betting authority.

Strict chronology: for heldout year S, the underlying SDV score model is
refitted exclusively on years earlier than S. A simple residual correction
(or side selection) for holdout season S is estimated only from earlier
out-of-season predictions. Historical moneyline closes, when present, are
research benchmarks only — not verified executable DraftKings quotes.

SDV source files historically carry spread + total; moneyline coverage is
therefore expected to be sparse or absent. The study fails closed when
coverage is insufficient and never invents prices or promotes picks.
"""
from __future__ import annotations

import argparse
import json
import re
from math import isfinite
from pathlib import Path

FAMILY = "PRIOR_CURRENT_BLEND"
ALPHA = 300.0
CONSTANTS = {"prior_equivalent_games": 4}
# Fixed before any evaluation. Points of model edge required to take a side.
THRESHOLD = 3.0
FIRST_TEST = 2021
BREAKEVEN = 110 / 210


def _finite_number(value):
    """Research inputs must be actual finite numbers, never bool or text."""
    return (not isinstance(value, bool)
            and isinstance(value, (int, float))
            and isfinite(value))


def fit_residual(data):
    """OLS residual on model_margin vs realized margin; used only for research screening."""
    # Integrity precedes coverage: a short sample must not hide a corrupt
    # source row behind INSUFFICIENT_CHRONO_TRAINING.
    if any(not _finite_number(r.get("model_margin"))
           or not _finite_number(r.get("actual_margin")) for r in data):
        raise ValueError("CFB_ML_CHRONO_TRAINING_NONFINITE_OR_NONNUMERIC")
    if len(data) < 300 or len({x["season"] for x in data}) < 3:
        raise ValueError("CFB_ML_CHRONO_TRAINING_INSUFFICIENT")
    xs = [r["model_margin"] for r in data]
    ys = [r["actual_margin"] for r in data]
    a = sum(xs) / len(xs)
    b = sum(ys) / len(ys)
    xx = sum((x - a) ** 2 for x in xs)
    if xx < 1e-8:
        raise ValueError("CFB_ML_CHRONO_MODEL_VARIANCE_ZERO")
    weight = sum((x - a) * (y - b) for x, y in zip(xs, ys)) / xx
    offset = b - weight * a
    if not (isfinite(weight) and isfinite(offset)):
        raise ValueError("CFB_ML_CHRONO_FIT_NONFINITE")
    return {
        "intercept": offset,
        "weight": weight,
        "train_n": len(data),
        "last_train_season": max(r["season"] for r in data),
    }


def chronological_ml_predictions(rows):
    from sportsedge.sports.cfb.sportsdataverse_candidate_model import fit_native_score_model
    seasons = sorted({int(r["season"]) for r in rows})
    out = {}
    for season in seasons:
        train = [r for r in rows if int(r["season"]) < season]
        hold = [r for r in rows if int(r["season"]) == season]
        if len(train) < 300 or not hold:
            continue
        fit = fit_native_score_model(
            train, family=FAMILY, ridge_alpha=ALPHA, constants=CONSTANTS
        )
        for g in hold:
            h, a = fit.predict_means(g, CONSTANTS)
            gid = str(g["game_id"])
            if gid in out:
                raise ValueError("CFB_ML_CHRONO_GAME_DUPLICATE")
            out[gid] = {
                "season": season,
                "model_margin": h - a,
                "actual_margin": float(g["home_points"]) - float(g["away_points"]),
                "home_won": float(g["home_points"]) > float(g["away_points"]),
            }
    return out


def _american_odd(value):
    """Strict integer American odds; reject booleans, floats and malformed text."""
    if type(value) is int:
        odds = value
    elif isinstance(value, str) and re.fullmatch(r"[+-]?[0-9]+", value.strip()):
        odds = int(value.strip())
    else:
        return None
    return odds if abs(odds) >= 100 else None


def paired_moneylines(preds, cache):
    """Research-only two-sided game/book candidates; never authenticated quotes.

    A pair must be recorded in *one* cache row under a named provider, with
    distinct home and away odds. Legacy scalar "moneyline" / "ml" fields,
    one-sided values, and nested cross-book records are not admitted.
    The archive has no independent quote timestamp, so even surviving pairs
    cannot establish DK execution, CLV, or real moneyline ROI.
    """
    out = []
    for year in range(2016, 2026):
        archive = cache.get(f"lines_{year}") or {}
        if not isinstance(archive, dict):
            continue
        for gid, entry in archive.items():
            p = preds.get(str(gid))
            if p is None:
                continue
            if p["season"] != year:
                raise ValueError("CFB_ML_CHRONO_SEASON_ID_MISMATCH")
            if not isinstance(entry, dict):
                continue
            provider = entry.get("provider")
            if type(provider) is not str or not provider.strip():
                continue
            home = _american_odd(entry.get("home_moneyline", entry.get("home_ml")))
            away = _american_odd(entry.get("away_moneyline", entry.get("away_ml")))
            if home is None or away is None:
                continue
            out.append({
                "game_id": str(gid),
                "season": year,
                "provider": provider.strip(),
                "model_margin": p["model_margin"],
                "actual_margin": p["actual_margin"],
                "home_won": p["home_won"],
                "home_ml": home,
                "away_ml": away,
                "quote_timestamp": None,
                "authenticated_draftkings": False,
            })
    return out


def grade(rows, fit, threshold=THRESHOLD):
    """Side selection on calibrated model margin; research-only grading."""
    if (not _finite_number(threshold) or threshold <= 0
            or not _finite_number(fit.get("intercept"))
            or not _finite_number(fit.get("weight"))):
        raise ValueError("CFB_ML_CHRONO_GRADE_INVALID_FIT")
    if any(not _finite_number(r.get("model_margin"))
           or type(r.get("home_won")) is not bool for r in rows):
        raise ValueError("CFB_ML_CHRONO_GRADE_INVALID_HOLDOUT")
    wins = losses = pushes = 0
    direction = {"home": 0, "away": 0}
    for r in rows:
        signed = fit["intercept"] + fit["weight"] * r["model_margin"]
        if not isfinite(signed):
            raise ValueError("CFB_ML_CHRONO_GRADE_NONFINITE_SCORE")
        if abs(signed) < threshold:
            continue
        side_home = signed > 0
        direction["home" if side_home else "away"] += 1
        # Research proxy: did the selected side win the game?
        if side_home == r["home_won"]:
            wins += 1
        else:
            losses += 1
    n = wins + losses
    return {
        "games": len(rows),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "decisions": n,
        "win_rate": round(wins / n, 5) if n else None,
        "synthetic_flat_minus_110_winner_return": round((wins * 100 / 110 - losses) / n, 5) if n else None,
        "selections": direction,
    }


def study(paired):
    folds = []
    for year in sorted({int(r["season"]) for r in paired}):
        if year < FIRST_TEST:
            continue
        train = [r for r in paired if r["season"] < year]
        test = [r for r in paired if r["season"] == year]
        if not test:
            continue
        try:
            fit = fit_residual(train)
        except ValueError as exc:
            # Only expected insufficient training / zero variance may skip a fold.
            # Invalid or nonfinite source rows must never be relabeled as a
            # mere coverage shortfall by silently dropping every later fold.
            if str(exc) in (
                "CFB_ML_CHRONO_TRAINING_INSUFFICIENT",
                "CFB_ML_CHRONO_MODEL_VARIANCE_ZERO",
            ):
                continue
            raise
        if fit["last_train_season"] >= year:
            raise ValueError("CFB_ML_CHRONO_LOOKAHEAD")
        row = grade(test, fit)
        folds.append({
            "season": year,
            **row,
            "fit": {
                "intercept": round(fit["intercept"], 5),
                "weight": round(fit["weight"], 5),
                "train_n": fit["train_n"],
                "max_train_season": fit["last_train_season"],
            },
        })
    w = sum(x["wins"] for x in folds)
    l = sum(x["losses"] for x in folds)
    n = w + l
    yr_positive = sum(
        x["synthetic_flat_minus_110_winner_return"] is not None and x["synthetic_flat_minus_110_winner_return"] > 0
        for x in folds
    )
    roi = (w * 100 / 110 - l) / n if n else None
    # Research-only screen. Even when it clears, source is not executable DK.
    status = (
        "RESEARCH_SCREEN_MET_NOT_FORWARD_VALIDATED"
        if n >= 200 and len(folds) >= 5 and yr_positive >= 4
        and roi is not None and roi >= 0.02
        else "NO_HISTORICALLY_VERIFIED_EDGE"
    )
    if not paired:
        status = "BLOCKED_NO_MONEYLINE_COVERAGE"
    elif not folds:
        status = "BLOCKED_INSUFFICIENT_CHRONO_TRAINING"
    elif n == 0:
        status = "BLOCKED_NO_ELIGIBLE_DECISIONS"
    return {
        "schema": "CFB_CHRONO_MONEYLINE_RESIDUAL_V1",
        "status": status,
        "family": FAMILY,
        "backtest_reference": "UNAUTHENTICATED_TWO_SIDED_PRICE_CANDIDATE_ONLY",
        "selection_threshold_points": THRESHOLD,
        "assumed_american_odds": -110,
        "pooled": {
            "wins": w,
            "losses": l,
            "decisions": n,
            "win_rate": round(w / n, 5) if n else None,
            "synthetic_flat_minus_110_winner_return": round(roi, 5) if roi is not None else None,
            "positive_synthetic_return_seasons": yr_positive,
        },
        "folds": folds,
        "authority": {
            "model_p": False,
            "bets": False,
            "staking": False,
            "official": False,
            "forward_validated": False,
            "dk_price_authenticated": False,
            "quote_timestamp_verified": False,
            "observed_price_roi": False,
            "no_backfill": True,
        },
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args(argv)
    from scripts.backtest_cfb_sdv_vs_lines import load_rows
    from sportsedge.sports.cfb.cfbd_issue_cache import load_cache
    rows = load_rows(args.rows)
    predictions = chronological_ml_predictions(rows)
    market = load_cache(issue=1475)
    paired = paired_moneylines(predictions, market)
    report = study(paired)
    report["source_coverage"] = {
        "training_rows": len(rows),
        "chrono_predictions": len(predictions),
        "two_sided_unverified_price_candidates": len(paired),
        "cache_issue": 1475,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        "CFB_ML_CHRONO_STUDY",
        json.dumps(
            {
                "status": report["status"],
                "pooled": report["pooled"],
                "coverage": report["source_coverage"],
            },
            sort_keys=True,
        ),
    )


if __name__ == "__main__":
    main()
