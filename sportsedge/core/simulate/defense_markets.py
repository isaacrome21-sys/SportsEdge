"""Deterministic defensive-market read-outs over shared Engine A+B paths."""

from __future__ import annotations

from collections.abc import Iterable
from math import isfinite

from .defense_full_game import FullGameDefensivePath
from .defense_usage import AttributedDefensivePath, DefenderUsageProfile


_PLAYER_STAT_ALIASES = {
    "player_sacks": "sacks",
    "sacks": "sacks",
    "tackles_assists": "tackles_assists",
    "tackles+assists": "tackles_assists",
    "player_interceptions": "interceptions",
    "interceptions": "interceptions",
}
_TEAM_STAT_ALIASES = {
    "team_sacks": "team_sacks",
    "team_turnovers": "team_turnovers",
}

_DefensivePath = AttributedDefensivePath | FullGameDefensivePath


def _paths(paths: Iterable[_DefensivePath]) -> list[_DefensivePath]:
    data = list(paths)
    if not data:
        raise ValueError("ATTRIBUTED_DEFENSIVE_PATHS_EMPTY")
    if any(not isinstance(path, (AttributedDefensivePath, FullGameDefensivePath)) for path in data):
        raise TypeError("ATTRIBUTED_DEFENSIVE_PATH_REQUIRED")
    game_ids = {path.base_path.game_id for path in data}
    if len(game_ids) != 1:
        raise ValueError("DEFENSE_MARKET_GAME_ID_MISMATCH")
    return data


def _three_way(values: list[float], line: float) -> dict[str, float]:
    if not values:
        raise ValueError("DEFENSE_MARKET_VALUES_EMPTY")
    threshold = float(line)
    if not isfinite(threshold):
        raise ValueError("DEFENSE_MARKET_LINE_NONFINITE")
    denominator = float(len(values))
    return {
        "over": sum(value > threshold for value in values) / denominator,
        "under": sum(value < threshold for value in values) / denominator,
        "push": sum(value == threshold for value in values) / denominator,
    }


def _profile(path: _DefensivePath, player_id: str) -> DefenderUsageProfile:
    matches = [
        player
        for usage in (path.home_defense, path.away_defense)
        for player in usage.players
        if player.player_id == player_id
    ]
    if len(matches) != 1:
        raise ValueError(f"DEFENDER_NOT_IN_USAGE_TREE:{player_id}")
    return matches[0]


def derive_defender_stat_market(
    paths: Iterable[_DefensivePath],
    *,
    player_id: str,
    stat: str,
    line: float,
    tackle_settlement_provider: str | None = None,
) -> dict[str, float]:
    """Price one defender prop from regulation-only or full-game attribution.

    Full-game sportsbook props should pass ``FullGameDefensivePath`` instances so
    any simulated overtime events are included. Tackle+assist markets require an
    explicit settlement-provider binding because official/stat-provider tackle
    credit can be corrected after initial grading.
    """

    data = _paths(paths)
    player = str(player_id).strip()
    if not player:
        raise ValueError("DEFENDER_ID_REQUIRED")
    normalized = str(stat).strip().lower()
    if normalized not in _PLAYER_STAT_ALIASES:
        raise ValueError(f"UNSUPPORTED_DEFENDER_STAT:{stat}")
    stat_key = _PLAYER_STAT_ALIASES[normalized]
    if stat_key == "tackles_assists" and not str(tackle_settlement_provider or "").strip():
        raise ValueError("TACKLE_SETTLEMENT_PROVIDER_REQUIRED")

    profiles = [_profile(path, player) for path in data]
    identity = {(profile.team, profile.position) for profile in profiles}
    if len(identity) != 1:
        raise ValueError("DEFENDER_USAGE_IDENTITY_MISMATCH")
    if any(profile.active is None for profile in profiles):
        raise ValueError(f"DEFENDER_PARTICIPATION_UNRESOLVED:{player}")
    if any(profile.active is not True for profile in profiles):
        raise ValueError(f"DEFENDER_INACTIVE:{player}")

    values = [float(path.player_stats()[player][stat_key]) for path in data]
    return _three_way(values, line)


def derive_team_defense_stat_market(
    paths: Iterable[_DefensivePath],
    *,
    team: str,
    stat: str,
    line: float,
) -> dict[str, float]:
    """Price team sacks/turnovers from the same attributed Engine A paths."""

    data = _paths(paths)
    team_id = str(team).strip()
    if not team_id:
        raise ValueError("DEFENSE_TEAM_REQUIRED")
    teams = {data[0].base_path.home_team, data[0].base_path.away_team}
    if team_id not in teams:
        raise ValueError(f"DEFENSE_TEAM_NOT_IN_GAME:{team_id}")
    normalized = str(stat).strip().lower()
    if normalized not in _TEAM_STAT_ALIASES:
        raise ValueError(f"UNSUPPORTED_TEAM_DEFENSE_STAT:{stat}")
    stat_key = _TEAM_STAT_ALIASES[normalized]
    values = [float(path.team_stats()[team_id][stat_key]) for path in data]
    return _three_way(values, line)
