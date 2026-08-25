"""Deterministic player-market read-outs over shared Engine A+B paths.

Every sample is derived from an Engine A play path after Engine B attribution.
This module never resimulates attempts, carries, targets, yards or touchdowns
and never consumes sportsbook price as a predictive input.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from math import isfinite
from typing import Any

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
    "rush_yards": "rushing_yards",
    "rushing_yards": "rushing_yards",
    "rush_attempts": "rush_attempts",
    "receiving_yards": "receiving_yards",
    "receptions": "receptions",
    "targets": "targets",
    "longest_completion": "longest_completion",
    "longest_reception": "longest_reception",
    "longest_rush": "longest_rush",
    "pass_plus_rush_yards": "pass_plus_rush_yards",
    "rush_plus_rec_yards": "rush_plus_receiving_yards",
    "rush_plus_receiving_yards": "rush_plus_receiving_yards",
}

_STAT_MARKETS = {
    "passing_yards": "passing_yards",
    "completions": "completions",
    "attempts": "pass_attempts",
    "passing_tds": "passing_tds",
    "interceptions": "interceptions",
    "rush_yards": "rushing_yards",
    "longest_completion": "longest_completion",
    "pass_plus_rush_yards": "pass_plus_rush_yards",
    "rushing_yards": "rushing_yards",
    "receiving_yards": "receiving_yards",
    "receptions": "receptions",
    "rush_attempts": "rush_attempts",
    "targets": "targets",
    "rush_plus_rec_yards": "rush_plus_receiving_yards",
    "longest_reception": "longest_reception",
    "longest_rush": "longest_rush",
}

_BINARY_TD_MARKETS = {"anytime_td", "first_td", "two_plus_td"}


def _paths(paths: Iterable[AttributedFootballPath]) -> list[AttributedFootballPath]:
    materialized = list(paths)
    if not materialized:
        raise ValueError("ATTRIBUTED_PATHS_EMPTY")
    if any(not isinstance(path, AttributedFootballPath) for path in materialized):
        raise TypeError("ATTRIBUTED_FOOTBALL_PATH_REQUIRED")
    game_ids = {path.base_path.game_id for path in materialized}
    if len(game_ids) != 1:
        raise ValueError("PLAYER_MARKET_GAME_ID_MISMATCH")
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


def _price(samples: list[float], line: float) -> dict[str, float]:
    if not samples:
        raise ValueError("PLAYER_MARKET_SAMPLES_REQUIRED")
    threshold = float(line)
    if not isfinite(threshold):
        raise ValueError("PLAYER_MARKET_LINE_NONFINITE")
    n = float(len(samples))
    return {
        "over": sum(value > threshold for value in samples) / n,
        "under": sum(value < threshold for value in samples) / n,
        "push": sum(value == threshold for value in samples) / n,
    }


def _identity(path: AttributedFootballPath) -> tuple[Any, ...]:
    return (
        path.base_path.game_id,
        path.base_path.home_team,
        path.base_path.away_team,
        tuple(player.player_id for player in path.home_usage.players),
        tuple(player.player_id for player in path.away_usage.players),
        path.home_usage.quarterback_id,
        path.away_usage.quarterback_id,
    )


def _first_td_scorer(path: AttributedFootballPath) -> str | None:
    for attributed in path.plays:
        play = attributed.base_play
        if play.points != 7 or play.play_type.upper() not in {"PASS", "RUSH"}:
            continue
        scorer = attributed.touchdown_scorer_id
        if not scorer:
            raise ValueError("FIRST_TD_SCORER_UNRESOLVED")
        return scorer
    return None


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
        values.append(float(stats[player][stat_key]))

    return _price(values, threshold)


def derive_player_market_readouts(
    attributed_paths: Iterable[AttributedFootballPath],
    *,
    lines: Mapping[str, Mapping[str, float]] | None = None,
) -> dict[str, dict[str, dict[str, object]]]:
    """Build per-player empirical distributions and binary TD probabilities.

    The player universe is the declared home/away usage roster, not merely the
    set of players who happened to receive a touch in the simulation ensemble.
    Zero-touch declared players are retained with zero-valued samples. Eligibility
    for an official wager remains a separate participation/settlement gate.
    """
    paths = list(attributed_paths)
    if not paths:
        raise ValueError("ATTRIBUTED_PATHS_REQUIRED")
    if any(not isinstance(path, AttributedFootballPath) for path in paths):
        raise TypeError("ATTRIBUTED_FOOTBALL_PATH_REQUIRED")

    identity = _identity(paths[0])
    if any(_identity(path) != identity for path in paths[1:]):
        raise ValueError("PLAYER_MARKET_ENSEMBLE_IDENTITY_MISMATCH")

    for path in paths:
        path.assert_reconciliation()

    player_ids = tuple(
        player.player_id
        for usage in (paths[0].home_usage, paths[0].away_usage)
        for player in usage.players
    )
    if len(player_ids) != len(set(player_ids)):
        raise ValueError("PLAYER_MARKET_PLAYER_ID_COLLISION")

    market_lines = {
        str(market): {str(player): float(line) for player, line in player_lines.items()}
        for market, player_lines in (lines or {}).items()
    }
    unsupported = sorted(set(market_lines) - set(_STAT_MARKETS))
    if unsupported:
        raise ValueError(f"PLAYER_MARKET_LINE_UNSUPPORTED:{unsupported[0]}")
    if "targets" in market_lines:
        raise ValueError("TARGET_SETTLEMENT_PROVIDER_REQUIRED")

    stats_by_sim = [path.player_stats() for path in paths]
    n = float(len(paths))
    readout: dict[str, dict[str, dict[str, object]]] = {
        market: {} for market in (*_STAT_MARKETS.keys(), *_BINARY_TD_MARKETS)
    }

    for player_id in player_ids:
        for market, stat_key in _STAT_MARKETS.items():
            samples = [float(stats[player_id][stat_key]) for stats in stats_by_sim]
            row: dict[str, object] = {
                "samples": tuple(samples),
                "mean": sum(samples) / n,
            }
            if player_id in market_lines.get(market, {}):
                row["price"] = _price(samples, market_lines[market][player_id])
            readout[market][player_id] = row

    first_td_counts: Counter[str] = Counter()
    for path in paths:
        scorer = _first_td_scorer(path)
        if scorer is not None:
            if scorer not in player_ids:
                raise ValueError("FIRST_TD_SCORER_NOT_IN_DECLARED_ROSTER")
            first_td_counts[scorer] += 1

    for player_id in player_ids:
        td_samples = [float(stats[player_id]["touchdowns"]) for stats in stats_by_sim]
        readout["anytime_td"][player_id] = {
            "samples": tuple(td_samples),
            "probability": sum(value >= 1.0 for value in td_samples) / n,
        }
        readout["two_plus_td"][player_id] = {
            "samples": tuple(td_samples),
            "probability": sum(value >= 2.0 for value in td_samples) / n,
        }
        readout["first_td"][player_id] = {
            "probability": first_td_counts[player_id] / n,
        }

    return readout
