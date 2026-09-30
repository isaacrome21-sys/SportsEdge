"""Strict-prior starting-pitcher run effect for the full-game distribution (audit fix D).

For every prior regular-season start, a starter's residual is the runs his team
allowed minus the opponent mean the production model would have used for that
game (defense blend -> calibrated_full_game_means). The effect of today's
starter on the opponent's scoring is the shrunk mean residual:

    effect = sum(residuals) / (starts + STARTER_PRIOR_STARTS)

The opponent's *calibrated* mean moves by STARTER_EFFECT_BETA * effect. Because
calibrated_full_game_means is affine in each raw mean, the feature row folds the
effect into the raw defense-blend mean (see raw_mean_shift), so the engines and
their frozen surface are unchanged.

Validation (2026 regular season; fit Apr-Jun, test Jul 1-Sep 27, 1,148 games)
versus the same distribution without starters: ML log-loss -0.0038 (1.9 SE),
RL -0.0034 (1.9 SE), O8.5 -0.0021 (1.1 SE).

Only final scores and announced probable starters from StatsAPI are used; no
sportsbook price enters the feature.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from statistics import fmean
from math import exp
from typing import Any, Mapping

from .v7_distribution import (
    V8_INDEPENDENT_HOME_FIELD_LOG,
    V8_INDEPENDENT_MEAN_SHRINK,
    calibrated_full_game_means,
)

STARTER_EFFECT_VERSION = "mlb_starter_run_effect_v1"
STARTER_EFFECT_BETA = 1.0
STARTER_PRIOR_STARTS = 40.0
MIN_RAW_MEAN_RUNS = 0.1
TEAM_WINDOW = 30
TEAM_MINIMUM = 10
TEAM_LOOKBACK_DAYS = 180


def _final_games(payload: Mapping[str, Any], target_date: date) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for block in payload.get("dates") or []:
        if not isinstance(block, Mapping):
            continue
        for game in block.get("games") or []:
            if not isinstance(game, Mapping):
                continue
            status = game.get("status") or {}
            if isinstance(status, Mapping) and status.get("abstractGameState") not in (None, "Final"):
                continue
            official = str(game.get("officialDate") or block.get("date") or "")[:10]
            if not official or official >= target_date.isoformat():
                continue
            teams = game.get("teams") or {}
            away = teams.get("away") or {}
            home = teams.get("home") or {}
            try:
                away_id = int((away.get("team") or {}).get("id"))
                home_id = int((home.get("team") or {}).get("id"))
                away_score = int(away.get("score"))
                home_score = int(home.get("score"))
            except (TypeError, ValueError, AttributeError):
                continue
            if min(away_score, home_score) < 0:
                continue

            def _pid(side: Mapping[str, Any]) -> int | None:
                pitcher = side.get("probablePitcher")
                if not isinstance(pitcher, Mapping):
                    return None
                try:
                    return int(pitcher.get("id"))
                except (TypeError, ValueError):
                    return None

            rows.append({
                "date": date.fromisoformat(official),
                "game_pk": str(game.get("gamePk")),
                "away": away_id, "home": home_id,
                "away_score": away_score, "home_score": home_score,
                "away_sp": _pid(away), "home_sp": _pid(home),
            })
    # One row per gamePk (postponed games can appear twice); keep the last listing.
    by_pk: dict[str, dict[str, Any]] = {}
    for row in sorted(rows, key=lambda r: (r["date"], r["game_pk"])):
        by_pk[row["game_pk"]] = row
    return sorted(by_pk.values(), key=lambda r: (r["date"], r["game_pk"]))


def starter_residual_history(payload: Mapping[str, Any], target_date: date) -> dict[int, list[float]]:
    """Chronological residuals per starter using only games before ``target_date``."""
    games = _final_games(payload, target_date)
    team_hist: dict[int, list[tuple[date, int, int]]] = defaultdict(list)
    residuals: dict[int, list[float]] = defaultdict(list)
    by_day: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for g in games:
        by_day[g["date"]].append(g)

    def profile(team: int, day: date) -> tuple[float, float] | None:
        rows = [r for r in team_hist.get(team, []) if r[0] >= day - timedelta(days=TEAM_LOOKBACK_DAYS)][-TEAM_WINDOW:]
        if len(rows) < TEAM_MINIMUM:
            return None
        return fmean(r[1] for r in rows), fmean(r[2] for r in rows)

    for day in sorted(by_day):
        todays = by_day[day]
        for g in todays:
            pa, ph = profile(g["away"], day), profile(g["home"], day)
            if pa is None or ph is None:
                continue
            away_mean = 0.5 * pa[0] + 0.5 * ph[1]
            home_mean = 0.5 * ph[0] + 0.5 * pa[1]
            cal_away, cal_home = calibrated_full_game_means(away_mean, home_mean)
            if g["away_sp"] is not None:
                residuals[g["away_sp"]].append(g["home_score"] - cal_home)
            if g["home_sp"] is not None:
                residuals[g["home_sp"]].append(g["away_score"] - cal_away)
        for g in todays:
            team_hist[g["away"]].append((day, g["away_score"], g["home_score"]))
            team_hist[g["home"]].append((day, g["home_score"], g["away_score"]))
    return dict(residuals)


def starter_run_effect(residuals: Mapping[int, list[float]], pitcher_id: int | None, *, prior_starts: float) -> dict[str, Any]:
    if pitcher_id is None:
        return {"pitcher_id": None, "starts": 0, "effect_runs": 0.0}
    rows = list(residuals.get(int(pitcher_id), []))
    effect = sum(rows) / (len(rows) + float(prior_starts))
    return {"pitcher_id": int(pitcher_id), "starts": len(rows), "effect_runs": float(effect)}


def raw_mean_shift(effect_runs: float, *, home: bool) -> float:
    """Raw-mean change that moves the calibrated mean by BETA * effect_runs."""
    half = V8_INDEPENDENT_HOME_FIELD_LOG / 2.0
    multiplier = V8_INDEPENDENT_MEAN_SHRINK * exp(half if home else -half)
    return STARTER_EFFECT_BETA * float(effect_runs) / multiplier


def apply_starter_effects(
    away_mean_runs: float,
    home_mean_runs: float,
    *,
    away_starter_effect_runs: float,
    home_starter_effect_runs: float,
) -> tuple[float, float]:
    """Away starter's effect lowers/raises HOME scoring and vice versa."""
    away = max(MIN_RAW_MEAN_RUNS, float(away_mean_runs) + raw_mean_shift(home_starter_effect_runs, home=False))
    home = max(MIN_RAW_MEAN_RUNS, float(home_mean_runs) + raw_mean_shift(away_starter_effect_runs, home=True))
    return away, home
