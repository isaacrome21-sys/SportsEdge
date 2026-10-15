"""Research-only, point-in-time empirical market prototype.

No quote collection, routing, deployment, calibration or PLAY authority.
Each observation is a complete, actually observed *prior* fixture or player game.
Never synthesize missing statistics as zero. A paired joint sample preserves
within-game dependence (unlike multiplying single-stat probabilities).
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Mapping

MIN_HISTORY = 20

# Each market maps to a statistic on ONE genuine historical game row.
SINGLE = {
    "MLB": {
        "TRIPLES": "triples",
        "PITCHER_RECORD_WIN": "pitcher_win",
        "FIRST_HOME_RUN": "first_home_run",
    },
    "NFL": {
        "longest_completion": "longest_completion",
        "targets": "targets",
        "longest_reception": "longest_reception",
        "longest_rush": "longest_rush",
        "two_plus_td": "touchdowns",
        "fg_made": "field_goals_made",
        "kicking_points": "kicking_points",
        "xp_made": "extra_points_made",
        "player_sacks": "player_sacks",
        "tackles_assists": "tackles_assists",
        "player_interceptions": "player_interceptions",
        "team_sacks": "team_sacks",
        "team_turnovers": "team_turnovers",
        "total_touchdowns": "total_touchdowns",
        "longest_fg_made": "longest_field_goal",
        "safety": "safeties",
        "defensive_special_teams_td": "defensive_special_teams_touchdowns",
        "largest_lead": "largest_lead",
    },
}
JOINT_SUM = {
    "MLB": {
        "EXTRA_BASE_HITS": ("doubles", "triples", "home_runs"),
        "HITS_RUNS_STOLEN_BASES": ("hits", "runs", "stolen_bases"),
        "RUNS_RBIS": ("runs", "rbis"),
        "HITS_STOLEN_BASES": ("hits", "stolen_bases"),
        "HITS_WALKS_STOLEN_BASES": ("hits", "walks", "stolen_bases"),
    },
    "NFL": {},
}

class EvidenceUnavailable(ValueError):
    """Missing, malformed or non-point-in-time research evidence."""


def _instant(value):
    if not isinstance(value, str):
        raise EvidenceUnavailable("TIMESTAMP_REQUIRED")
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceUnavailable("TIMESTAMP_INVALID") from exc
    if d.tzinfo is None:
        raise EvidenceUnavailable("TIMESTAMP_TZ_REQUIRED")
    return d.astimezone(timezone.utc)


def _number(row: Mapping, key: str):
    v = row.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not isfinite(v) or v < 0:
        raise EvidenceUnavailable("STAT_MISSING_OR_INVALID:" + key)
    return float(v)


def research_probability(*, sport: str, market: str, observations: list,
                         target_time: str, line: float | None = None,
                         side: str = "OVER", min_history: int = MIN_HISTORY):
    """P(event) estimated from *complete* pre-target rows, Laplace smoothed.

    Observations require unique fixture_id, observed_at (receipt) and
    game_end_at, with both timestamps strictly before target_time.
    Caller must separately prove fixture/player identity, source validity,
    participation, settlement conventions and lineup. This returns no
    fair odds, EV, staking authority or validated model probability.
    """
    fields = JOINT_SUM.get(sport, {}).get(market)
    single = SINGLE.get(sport, {}).get(market)
    if fields is None and single is None:
        raise EvidenceUnavailable("MARKET_NOT_IMPLEMENTED")
    if side not in ("OVER", "UNDER"):
        raise EvidenceUnavailable("SIDE_UNSUPPORTED")
    if market == "two_plus_td":
        if line is not None and line != 1.5:
            raise EvidenceUnavailable("TWO_PLUS_TD_LINE_MUST_BE_1_5")
        line = 1.5
    if isinstance(line, bool) or not isinstance(line, (int, float)) or not isfinite(line):
        raise EvidenceUnavailable("LINE_REQUIRED")
    if not isinstance(min_history, int) or isinstance(min_history, bool) or min_history < MIN_HISTORY:
        raise EvidenceUnavailable("HISTORY_FLOOR_20")
    if not isinstance(observations, list):
        raise EvidenceUnavailable("OBSERVATIONS_LIST_REQUIRED")
    target = _instant(target_time)
    ids = set()
    hits = 0
    total = 0
    for row in observations:
        if not isinstance(row, dict):
            raise EvidenceUnavailable("OBSERVATION_WRONG_TYPE")
        fixture = row.get("fixture_id")
        if not isinstance(fixture, str) or not fixture.strip() or fixture in ids:
            raise EvidenceUnavailable("FIXTURE_ID_MISSING_OR_DUPLICATE")
        ids.add(fixture)
        receipt = _instant(row.get("observed_at"))
        end = _instant(row.get("game_end_at"))
        if end >= target or receipt >= target or receipt < end:
            raise EvidenceUnavailable("NOT_STRICTLY_PRIOR_EVIDENCE")
        value = sum(_number(row, k) for k in fields) if fields else _number(row, single)
        hits += (value > line) if side == "OVER" else (value < line)
        total += 1
    if total < min_history:
        raise EvidenceUnavailable("INSUFFICIENT_COMPLETE_HISTORY")
    return {
        "sport": sport, "market": market, "side": side, "line": line,
        "research_frequency_smoothed": (hits + 1) / (total + 2),
        "sample_size": total, "successes": hits,
        "status": "RESEARCH_ONLY_UNVALIDATED",
        "eligibility": False, "play": False, "official_authority": False,
        "pricing_authority": False,
        "blocker": "NO_VALIDATION_AND_NO_CANONICAL_INTAKE",
    }
