"""Deterministic player-market read-outs over shared Engine A+B paths.

This module prices only statistics already produced by ``AttributedFootballPath``.
It does not resimulate attempts, carries, targets, yards or touchdowns. Markets
that require Engine C participation (for example full anytime-TD semantics with
return touchdowns) are intentionally outside this structural v1 surface.
"""

from __future__ import annotations

from collections.abc import Iterable
from math import isfinite

from .usage import AttributedFootballPath, PlayerUsageProfile


_STAT_ALIASES = {
    "attempts": "pass_attempts",
    "passing_attempts": "pass_attempts",
    "pass_attempts": "pass_attempts",
    "completions": "completions",
    "passing_yards": "passing_yards",
    "passing_tds": "passing_tds",
    "pass_tds": "passing_tds",
    "interceptions": "interceptions",
    "qb_interceptions": "interceptions",
    "rushing_yards": "rushing_yards",
    "rush_attempts": "rush_attempts",
    "receiving_yards": "receiving_yards",
    "receptions": "receptions",
    "targets": "targets",
    "longest_completion": "longest_completion",
    "longest_reception": "longest_reception",
    "longest_rush": "longest_rush",
    "pass_plus_rush_yards": "pass_plus_rush_yards",
    "rush_plus_receiving_yards": "rush_plus_receiving_yards",
}


def _paths(paths: Iterable[AttributedFootballPath]) -> list[AttributedFootballPath]:
    materialized = list(paths)
    if not materialized:
        raise ValueError("ATTRIBUTED_PATHS_EMPTY")
    if any(not isinstance(path, AttributedFootballPath) for path in materialized):
        raise TypeError("ATTRIBUTED_FOOTBALL_PATH_REQUIRED")
    game_ids = {path.base_path.game_id for path in materialized}
    if len(game_ids) != 1:
        raise ValueError("PLAYER_MARKET_GAME_ID_MISMATCH")
    identities = {(path.base_path.home_team, path.base_path.away_team) for path in materialized}
    if len(identities) != 1:
        raise ValueError("PLAYER_MARKET_TEAM_IDENTITY_MISMATCH")
    simulation_ids = [path.base_path.simulation_id for path in materialized]
    if len(set(simulation_ids)) != len(simulation_ids):
        raise ValueError("PLAYER_MARKET_DUPLICATE_SIMULATION_PATH")
    return materialized


def _player_profile(path: AttributedFootballPath, player_id: str) -> PlayerUsageProfile:
    matches = [
        player
        for usage in (path.home_usage, path.away_usage)
        for player in usage.players
        if player.player_id == player_id
    ]
    if len(matches) != 1:
        raise ValueError(f"PLAYER_NOT_IN_USAGE_TREE:{player_id}")
    return matches[0]


def _normalize_stat(stat: str) -> str:
    normalized = str(stat).strip().lower()
    if normalized not in _STAT_ALIASES:
        raise ValueError(f"UNSUPPORTED_PLAYER_STAT:{stat}")
    return _STAT_ALIASES[normalized]


def derive_player_stat_market(
    paths: Iterable[AttributedFootballPath],
    *,
    player_id: str,
    stat: str,
    line: float,
    target_settlement_provider: str | None = None,
) -> dict[str, float]:
    """Price one player over/under/push market from existing path-level stats.

    Target attribution is an internal intended-target identity until bound to a
    sportsbook/stat-provider definition. Therefore target markets fail closed
    unless ``target_settlement_provider`` is explicitly supplied.
    """

    materialized = _paths(paths)
    player = str(player_id).strip()
    if not player:
        raise ValueError("PLAYER_ID_REQUIRED")
    stat_key = _normalize_stat(stat)
    if isinstance(line, bool):
        raise ValueError("PLAYER_MARKET_LINE_BOOLEAN")
    threshold = float(line)
    if not isfinite(threshold):
        raise ValueError("PLAYER_MARKET_LINE_NONFINITE")
    if stat_key == "targets" and not str(target_settlement_provider or "").strip():
        raise ValueError("TARGET_SETTLEMENT_PROVIDER_REQUIRED")

    profiles = [_player_profile(path, player) for path in materialized]
    identity = {(profile.team, profile.position) for profile in profiles}
    if len(identity) != 1:
        raise ValueError("PLAYER_USAGE_IDENTITY_MISMATCH")
    if any(profile.active is None for profile in profiles):
        raise ValueError(f"PARTICIPATION_UNRESOLVED:{player}")
    if any(profile.active is not True for profile in profiles):
        raise ValueError(f"PLAYER_INACTIVE:{player}")

    values: list[float] = []
    for path in materialized:
        stats = path.player_stats()
        if player not in stats:
            raise ValueError(f"PLAYER_STATS_MISSING:{player}")
        if stat_key not in stats[player]:
            raise ValueError(f"PLAYER_STAT_MISSING:{stat_key}")
        value = float(stats[player][stat_key])
        if not isfinite(value):
            raise ValueError(f"PLAYER_STAT_NONFINITE:{stat_key}")
        values.append(value)

    denominator = float(len(values))
    return {
        "over": sum(value > threshold for value in values) / denominator,
        "under": sum(value < threshold for value in values) / denominator,
        "push": sum(value == threshold for value in values) / denominator,
    }
