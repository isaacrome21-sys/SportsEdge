"""Deterministic defensive-market read-outs over shared Engine A+B paths."""

from __future__ import annotations

from collections.abc import Iterable
from math import isfinite

from .defense_full_game import FullGameDefensivePath
from .defense_usage import AttributedDefensivePath, DefenderUsageProfile


_PLAYER_ALIASES = {
    "solo_tackles": "solo_tackles",
    "tackles_assists": "tackles_assists",
    "tackles+assists": "tackles_assists",
    "sacks": "sacks",
    "interceptions": "interceptions",
}
_TEAM_ALIASES = {
    "team_sacks": "team_sacks",
    "sacks": "team_sacks",
    "team_turnovers": "team_turnovers",
    "turnovers": "team_turnovers",
}


def _paths(
    paths: Iterable[AttributedDefensivePath | FullGameDefensivePath],
) -> list[AttributedDefensivePath | FullGameDefensivePath]:
    materialized = list(paths)
    if not materialized:
        raise ValueError("DEFENSIVE_PATHS_EMPTY")
    if any(not isinstance(path, (AttributedDefensivePath, FullGameDefensivePath)) for path in materialized):
        raise TypeError("ATTRIBUTED_DEFENSIVE_PATH_REQUIRED")
    game_ids = {
        path.game_id if isinstance(path, FullGameDefensivePath) else path.base_path.game_id
        for path in materialized
    }
    if len(game_ids) != 1:
        raise ValueError("DEFENSIVE_MARKET_GAME_ID_MISMATCH")
    return materialized


def _profile(
    path: AttributedDefensivePath | FullGameDefensivePath,
    player_id: str,
) -> DefenderUsageProfile:
    source = path.regulation if isinstance(path, FullGameDefensivePath) else path
    matches = [
        player
        for usage in (source.home_defense, source.away_defense)
        for player in usage.players
        if player.player_id == player_id
    ]
    if len(matches) != 1:
        raise ValueError(f"DEFENDER_NOT_IN_USAGE_TREE:{player_id}")
    return matches[0]


def _market(values: list[float], line: float) -> dict[str, float]:
    threshold = float(line)
    if not isfinite(threshold):
        raise ValueError("DEFENSIVE_MARKET_LINE_NONFINITE")
    denominator = float(len(values))
    return {
        "over": sum(value > threshold for value in values) / denominator,
        "under": sum(value < threshold for value in values) / denominator,
        "push": sum(value == threshold for value in values) / denominator,
    }


def derive_defender_stat_market(
    paths: Iterable[AttributedDefensivePath | FullGameDefensivePath],
    *,
    player_id: str,
    stat: str,
    line: float,
    tackle_settlement_provider: str | None = None,
) -> dict[str, float]:
    materialized = _paths(paths)
    player = str(player_id).strip()
    if not player:
        raise ValueError("DEFENDER_ID_REQUIRED")
    normalized = str(stat).strip().lower()
    if normalized not in _PLAYER_ALIASES:
        raise ValueError(f"UNSUPPORTED_DEFENDER_STAT:{stat}")
    stat_key = _PLAYER_ALIASES[normalized]
    if stat_key in {"solo_tackles", "tackles_assists"} and not str(tackle_settlement_provider or "").strip():
        raise ValueError("TACKLE_SETTLEMENT_PROVIDER_REQUIRED")

    profiles = [_profile(path, player) for path in materialized]
    identity = {(profile.team, profile.position) for profile in profiles}
    if len(identity) != 1:
        raise ValueError("DEFENDER_USAGE_IDENTITY_MISMATCH")
    if any(profile.active is None for profile in profiles):
        raise ValueError(f"DEFENDER_PARTICIPATION_UNRESOLVED:{player}")
    if any(profile.active is not True for profile in profiles):
        raise ValueError(f"DEFENDER_INACTIVE:{player}")

    values = []
    for path in materialized:
        stats = path.player_stats()
        if player not in stats or stat_key not in stats[player]:
            raise ValueError(f"DEFENDER_STAT_MISSING:{player}:{stat_key}")
        values.append(float(stats[player][stat_key]))
    return _market(values, line)


def derive_team_defense_stat_market(
    paths: Iterable[AttributedDefensivePath | FullGameDefensivePath],
    *,
    team: str,
    stat: str,
    line: float,
) -> dict[str, float]:
    materialized = _paths(paths)
    team_id = str(team).strip()
    if not team_id:
        raise ValueError("DEFENSE_TEAM_REQUIRED")
    normalized = str(stat).strip().lower()
    if normalized not in _TEAM_ALIASES:
        raise ValueError(f"UNSUPPORTED_TEAM_DEFENSE_STAT:{stat}")
    stat_key = _TEAM_ALIASES[normalized]

    values = []
    for path in materialized:
        stats = path.team_stats()
        if team_id not in stats or stat_key not in stats[team_id]:
            raise ValueError(f"TEAM_DEFENSE_STAT_MISSING:{team_id}:{stat_key}")
        values.append(float(stats[team_id][stat_key]))
    return _market(values, line)
