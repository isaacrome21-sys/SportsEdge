"""Deterministic kicker-market read-outs over resolved Engine A+C paths."""

from __future__ import annotations

from collections.abc import Iterable
from math import isfinite

from .special_teams import ResolvedFootballPath, SpecialTeamsProfile


_STAT_ALIASES = {
    "field_goals_made": "field_goals_made",
    "fg_made": "field_goals_made",
    "extra_points_made": "extra_points_made",
    "xp_made": "extra_points_made",
    "kicking_points": "kicking_points",
    "longest_field_goal": "longest_field_goal",
    "longest_fg": "longest_field_goal",
}


def _paths(paths: Iterable[ResolvedFootballPath]) -> list[ResolvedFootballPath]:
    materialized = list(paths)
    if not materialized:
        raise ValueError("RESOLVED_PATHS_EMPTY")
    if any(not isinstance(path, ResolvedFootballPath) for path in materialized):
        raise TypeError("RESOLVED_FOOTBALL_PATH_REQUIRED")
    game_ids = {path.base_path.game_id for path in materialized}
    if len(game_ids) != 1:
        raise ValueError("KICKER_MARKET_GAME_ID_MISMATCH")
    return materialized


def _bound_profile(path: ResolvedFootballPath, kicker_id: str) -> SpecialTeamsProfile:
    profiles = [
        profile
        for profile in (path.home_profile, path.away_profile)
        if profile is not None and profile.kicker_id == kicker_id
    ]
    if len(profiles) != 1:
        raise ValueError(f"KICKER_NOT_BOUND_TO_PATH:{kicker_id}")
    return profiles[0]


def _stat_value(path: ResolvedFootballPath, kicker_id: str, stat: str) -> float:
    events = [event for event in path.special_teams_events if event.kicker_id == kicker_id]
    if stat == "field_goals_made":
        return float(sum(event.event_type == "FG_MADE" for event in events))
    if stat == "extra_points_made":
        return float(sum(event.event_type == "XP_MADE" for event in events))
    if stat == "kicking_points":
        return float(
            sum(
                event.points
                for event in events
                if event.event_type in {"FG_MADE", "XP_MADE"}
            )
        )
    if stat == "longest_field_goal":
        made_distances = [
            int(event.kick_distance)
            for event in events
            if event.event_type == "FG_MADE" and event.kick_distance is not None
        ]
        return float(max(made_distances) if made_distances else 0)
    raise ValueError(f"UNSUPPORTED_KICKER_STAT:{stat}")


def derive_kicker_stat_market(
    paths: Iterable[ResolvedFootballPath],
    *,
    kicker_id: str,
    stat: str,
    line: float,
) -> dict[str, float]:
    """Price one kicker O/U/push market from existing Engine C outcomes."""

    materialized = _paths(paths)
    kicker = str(kicker_id).strip()
    if not kicker:
        raise ValueError("KICKER_ID_REQUIRED")
    normalized = str(stat).strip().lower()
    if normalized not in _STAT_ALIASES:
        raise ValueError(f"UNSUPPORTED_KICKER_STAT:{stat}")
    stat_key = _STAT_ALIASES[normalized]
    threshold = float(line)
    if not isfinite(threshold):
        raise ValueError("KICKER_MARKET_LINE_NONFINITE")

    profiles = [_bound_profile(path, kicker) for path in materialized]
    identity = {(profile.team, profile.kicker_id) for profile in profiles}
    if len(identity) != 1:
        raise ValueError("KICKER_PROFILE_IDENTITY_MISMATCH")
    if any(profile.kicker_active is None for profile in profiles):
        raise ValueError(f"KICKER_STATUS_UNRESOLVED:{kicker}")
    if any(profile.kicker_active is not True for profile in profiles):
        raise ValueError(f"KICKER_INACTIVE:{kicker}")

    values = [_stat_value(path, kicker, stat_key) for path in materialized]
    denominator = float(len(values))
    return {
        "over": sum(value > threshold for value in values) / denominator,
        "under": sum(value < threshold for value in values) / denominator,
        "push": sum(value == threshold for value in values) / denominator,
    }
