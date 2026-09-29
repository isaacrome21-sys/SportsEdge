"""Research-only MLB full-game run-environment adjustment.

This module is deliberately NOT Model_P.  It exists to diagnose the Sept. 29,
2026 full-game over bias without changing production, promotion, Truth Gate,
staking, or OFFICIAL authority.

The production manual MLB path currently builds full-game means from each
team's own recent runs scored.  This research lane instead combines strictly
prior offense with the opponent's strictly prior run prevention, then applies
an explicitly auditable current-starter adjustment.  Weather is consumed only
when outdoor exposure is known.  Retractable-roof UNKNOWN fails closed to a
neutral weather multiplier.

The temperature sensitivity is a research diagnostic, not a fitted SportsEdge
coefficient.  It uses the published Koch/Panorska 2000-2011 MLB cold/warm run
means (8.95 and 10.08 total runs) and normalizes each to their midpoint.  The
factor is applied only for <60F or >83F, the study's reported cold/warm bins;
60-83F is neutral.  It must not be promoted without chronological calibration.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from math import isfinite
from statistics import fmean
from typing import Any, Callable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json

from .mlb_generic_features import MLBGenericFeatureError, MLBGenericHistorySource, _outs_from_ip

RESEARCH_VERSION = "mlb_context_adjusted_runs_research_v1"
TEMPERATURE_RULE_VERSION = "koch_panorska_2013_midpoint_v0"
COLD_RUNS = 8.95
WARM_RUNS = 10.08
TEMP_MIDPOINT_RUNS = (COLD_RUNS + WARM_RUNS) / 2.0
COLD_TEMP_F = 60.0
WARM_TEMP_F = 83.0


class MLBContextAdjustedResearchError(ValueError):
    pass


@dataclass(frozen=True)
class TeamRunProfile:
    team_id: int
    games: int
    runs_for_mean: float
    runs_against_mean: float


@dataclass(frozen=True)
class StarterProfile:
    player_id: int
    starts: int
    er_per_9: float | None
    mean_outs: float | None
    status: str


@dataclass(frozen=True)
class WeatherAdjustment:
    multiplier: float
    applied: bool
    reason: str
    temperature_f: float | None
    roof_type: str | None
    roof_state: str | None
    rule_version: str = TEMPERATURE_RULE_VERSION


def _read_json(url: str, *, opener: Callable = urlopen) -> Mapping[str, Any]:
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "SportsEdge-MLB-Research/1.0"})
    try:
        with opener(req, timeout=30) as response:
            value = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise MLBContextAdjustedResearchError(f"RESEARCH_FETCH_FAILED:{url}") from exc
    if not isinstance(value, Mapping):
        raise MLBContextAdjustedResearchError("RESEARCH_FETCH_NOT_OBJECT")
    return value


def recent_team_run_profile(
    *,
    team_id: int,
    target_date: date,
    window: int = 30,
    minimum: int = 10,
    opener: Callable = urlopen,
) -> TeamRunProfile:
    """Return strictly-prior recent runs for/against from final regular-season games."""
    if window < minimum or minimum < 1:
        raise MLBContextAdjustedResearchError("invalid run-profile window/minimum")
    start_date = target_date - timedelta(days=180)
    end_date = target_date - timedelta(days=1)
    query = urlencode({
        "sportId": 1,
        "teamId": int(team_id),
        "gameType": "R",
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
    })
    payload = _read_json(f"https://statsapi.mlb.com/api/v1/schedule?{query}", opener=opener)
    rows: list[tuple[str, int, int]] = []
    for block in payload.get("dates") or []:
        if not isinstance(block, Mapping):
            continue
        for game in block.get("games") or []:
            if not isinstance(game, Mapping):
                continue
            status = game.get("status") or {}
            if not isinstance(status, Mapping) or str(status.get("abstractGameState") or "") != "Final":
                continue
            official = str(game.get("officialDate") or block.get("date") or "")[:10]
            if not official or official >= target_date.isoformat():
                continue
            teams = game.get("teams") or {}
            if not isinstance(teams, Mapping):
                continue
            away = teams.get("away") or {}
            home = teams.get("home") or {}
            if not isinstance(away, Mapping) or not isinstance(home, Mapping):
                continue
            away_team = away.get("team") or {}
            home_team = home.get("team") or {}
            try:
                away_id = int(away_team.get("id"))
                home_id = int(home_team.get("id"))
                away_score = int(away.get("score"))
                home_score = int(home.get("score"))
            except (TypeError, ValueError):
                continue
            if int(team_id) == away_id:
                rows.append((official, away_score, home_score))
            elif int(team_id) == home_id:
                rows.append((official, home_score, away_score))
    rows.sort(key=lambda row: row[0])
    rows = rows[-window:]
    if len(rows) < minimum:
        raise MLBContextAdjustedResearchError(f"team:{team_id}: insufficient final-game sample {len(rows)}<{minimum}")
    return TeamRunProfile(
        team_id=int(team_id),
        games=len(rows),
        runs_for_mean=float(fmean(float(row[1]) for row in rows)),
        runs_against_mean=float(fmean(float(row[2]) for row in rows)),
    )


def recent_starter_profile(
    *,
    history: MLBGenericHistorySource,
    player_id: int,
    target_date: date,
    window: int = 12,
    minimum: int = 3,
) -> StarterProfile:
    """Summarize a probable starter's strictly-prior starts using ER and outs."""
    rows = history.player_rows(player_id=int(player_id), group="pitching", target_date=target_date)
    starts: list[tuple[float, float]] = []
    for row in rows:
        stat = row.get("stat") or {}
        if not isinstance(stat, Mapping):
            continue
        try:
            if float(stat.get("gamesStarted", 0) or 0) < 1:
                continue
            outs = float(_outs_from_ip(stat.get("inningsPitched")))
            er = float(stat.get("earnedRuns", 0) or 0)
        except (TypeError, ValueError, MLBGenericFeatureError):
            continue
        if outs <= 0 or er < 0 or not isfinite(outs) or not isfinite(er):
            continue
        starts.append((outs, er))
    starts = starts[-window:]
    if len(starts) < minimum:
        return StarterProfile(int(player_id), len(starts), None, None, "INSUFFICIENT_PRIOR_STARTS")
    total_outs = sum(row[0] for row in starts)
    total_er = sum(row[1] for row in starts)
    if total_outs <= 0:
        return StarterProfile(int(player_id), len(starts), None, None, "ZERO_PRIOR_OUTS")
    er_per_9 = 27.0 * total_er / total_outs
    mean_outs = float(fmean(row[0] for row in starts))
    return StarterProfile(int(player_id), len(starts), float(er_per_9), mean_outs, "AVAILABLE")


def weather_adjustment(weather_roof: Mapping[str, Any] | None) -> WeatherAdjustment:
    """Convert sourced pregame weather into a fail-closed research multiplier.

    Wind is intentionally not converted to runs here because this bundle does not
    bind wind to verified park orientation.  Low/unknown wind therefore cannot be
    turned into an invented run effect.
    """
    lane = weather_roof if isinstance(weather_roof, Mapping) else {}
    roof_type = str(lane.get("roof_type") or "").strip() or None
    roof_state = str(lane.get("roof_state") or "").strip() or None
    forecast = lane.get("forecast") or {}
    try:
        temp = float(forecast.get("temperature")) if isinstance(forecast, Mapping) and forecast.get("temperature") is not None else None
    except (TypeError, ValueError):
        temp = None

    rt = (roof_type or "").upper()
    rs = (roof_state or "").upper()
    if rt == "RETRACTABLE" and rs != "OPEN":
        return WeatherAdjustment(1.0, False, "WEATHER_NOT_APPLIED_RETRACTABLE_ROOF_NOT_CONFIRMED_OPEN", temp, roof_type, roof_state)
    if rt in {"DOME", "FIXED", "CLOSED"} or rs == "CLOSED":
        return WeatherAdjustment(1.0, False, "WEATHER_NOT_APPLIED_INDOOR", temp, roof_type, roof_state)
    if rt != "OPEN" and rs != "OPEN":
        return WeatherAdjustment(1.0, False, "WEATHER_NOT_APPLIED_OUTDOOR_EXPOSURE_UNKNOWN", temp, roof_type, roof_state)
    if temp is None or not isfinite(temp):
        return WeatherAdjustment(1.0, False, "WEATHER_NOT_APPLIED_TEMPERATURE_MISSING", temp, roof_type, roof_state)
    if temp < COLD_TEMP_F:
        return WeatherAdjustment(COLD_RUNS / TEMP_MIDPOINT_RUNS, True, "COLD_BIN", temp, roof_type, roof_state)
    if temp > WARM_TEMP_F:
        return WeatherAdjustment(WARM_RUNS / TEMP_MIDPOINT_RUNS, True, "WARM_BIN", temp, roof_type, roof_state)
    return WeatherAdjustment(1.0, True, "AVERAGE_TEMPERATURE_BIN_NEUTRAL", temp, roof_type, roof_state)


def _starter_multiplier(*, starter: StarterProfile, defense_runs_allowed: float) -> tuple[float, float, str]:
    """Return (multiplier, starter_share, reason) against the opponent baseline.

    The comparison is intentionally simple and auditable: recent starter ER/9 is
    compared with his club's recent runs allowed per game, and only the share of
    a game represented by his recent mean outs receives that relative adjustment.
    """
    if starter.status != "AVAILABLE" or starter.er_per_9 is None or starter.mean_outs is None:
        return 1.0, 0.0, f"STARTER_NEUTRAL:{starter.status}"
    if not isfinite(defense_runs_allowed) or defense_runs_allowed <= 0:
        return 1.0, 0.0, "STARTER_NEUTRAL:DEFENSE_BASELINE_INVALID"
    share = max(0.0, min(0.80, starter.mean_outs / 27.0))
    relative = max(0.55, min(1.45, starter.er_per_9 / defense_runs_allowed))
    multiplier = (1.0 - share) + share * relative
    return float(multiplier), float(share), "APPLIED"


def context_adjusted_means(
    *,
    away: TeamRunProfile,
    home: TeamRunProfile,
    away_starter: StarterProfile,
    home_starter: StarterProfile,
    weather: WeatherAdjustment,
) -> dict[str, Any]:
    """Build research means from offense, opponent prevention, starters and weather."""
    away_pre_starter = 0.5 * away.runs_for_mean + 0.5 * home.runs_against_mean
    home_pre_starter = 0.5 * home.runs_for_mean + 0.5 * away.runs_against_mean

    away_starter_mult, away_starter_share, away_starter_reason = _starter_multiplier(
        starter=home_starter, defense_runs_allowed=home.runs_against_mean,
    )
    home_starter_mult, home_starter_share, home_starter_reason = _starter_multiplier(
        starter=away_starter, defense_runs_allowed=away.runs_against_mean,
    )

    away_mean = max(0.05, away_pre_starter * away_starter_mult * weather.multiplier)
    home_mean = max(0.05, home_pre_starter * home_starter_mult * weather.multiplier)
    return {
        "research_version": RESEARCH_VERSION,
        "label": "NOT_MODEL_P",
        "promotion_evidence": False,
        "model_p_eligible": False,
        "away_mean_runs": float(away_mean),
        "home_mean_runs": float(home_mean),
        "total_mean_runs": float(away_mean + home_mean),
        "components": {
            "away_team": asdict(away),
            "home_team": asdict(home),
            "away_probable_starter": asdict(away_starter),
            "home_probable_starter": asdict(home_starter),
            "away_pre_starter_mean": float(away_pre_starter),
            "home_pre_starter_mean": float(home_pre_starter),
            "away_scoring_starter_multiplier": away_starter_mult,
            "home_scoring_starter_multiplier": home_starter_mult,
            "away_scoring_starter_share": away_starter_share,
            "home_scoring_starter_share": home_starter_share,
            "away_scoring_starter_reason": away_starter_reason,
            "home_scoring_starter_reason": home_starter_reason,
            "weather": asdict(weather),
        },
    }
