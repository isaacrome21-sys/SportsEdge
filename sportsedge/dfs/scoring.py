from __future__ import annotations

from math import sqrt
from typing import Mapping

from .types import DKPlayer, Projection


def _v(stats: Mapping[str, float], key: str) -> float:
    return float(stats.get(key, 0.0) or 0.0)


def football_expected_dk_points(stats: Mapping[str, float]) -> float:
    """Expected DraftKings NFL/CFB offensive fantasy points from stat expectations.

    Bonus keys are probabilities in [0,1]: p_pass_300, p_rush_100, p_rec_100.
    """
    return (
        0.04 * _v(stats, "pass_yards")
        + 4.0 * _v(stats, "pass_tds")
        - 1.0 * _v(stats, "interceptions")
        + 0.10 * _v(stats, "rush_yards")
        + 6.0 * _v(stats, "rush_tds")
        + 1.0 * _v(stats, "receptions")
        + 0.10 * _v(stats, "rec_yards")
        + 6.0 * _v(stats, "rec_tds")
        - 1.0 * _v(stats, "fumbles_lost")
        + 2.0 * _v(stats, "two_point_conversions")
        + 6.0 * _v(stats, "return_tds")
        + 3.0 * _v(stats, "p_pass_300")
        + 3.0 * _v(stats, "p_rush_100")
        + 3.0 * _v(stats, "p_rec_100")
    )


def mlb_hitter_expected_dk_points(stats: Mapping[str, float]) -> float:
    return (
        3.0 * _v(stats, "singles")
        + 5.0 * _v(stats, "doubles")
        + 8.0 * _v(stats, "triples")
        + 10.0 * _v(stats, "home_runs")
        + 2.0 * _v(stats, "rbi")
        + 2.0 * _v(stats, "runs")
        + 2.0 * _v(stats, "walks")
        + 2.0 * _v(stats, "hbp")
        + 5.0 * _v(stats, "stolen_bases")
    )


def mlb_pitcher_expected_dk_points(stats: Mapping[str, float]) -> float:
    outs = _v(stats, "outs")
    if not outs and "innings" in stats:
        outs = 3.0 * _v(stats, "innings")
    return (
        0.75 * outs
        + 2.0 * _v(stats, "strikeouts")
        + 4.0 * _v(stats, "win_probability")
        - 2.0 * _v(stats, "earned_runs")
        - 0.6 * _v(stats, "hits_allowed")
        - 0.6 * _v(stats, "walks_allowed")
        - 0.6 * _v(stats, "hbp_allowed")
        + 2.5 * _v(stats, "complete_game_probability")
        + 2.5 * _v(stats, "cg_shutout_probability")
        + 5.0 * _v(stats, "no_hitter_probability")
    )


def projection_from_stats(
    player: DKPlayer,
    sport: str,
    stats: Mapping[str, float],
    *,
    source: str,
) -> Projection:
    sport = sport.upper()
    if sport in {"NFL", "CFB"}:
        mean = football_expected_dk_points(stats)
    elif sport == "MLB" and "P" in player.positions:
        mean = mlb_pitcher_expected_dk_points(stats)
    elif sport == "MLB":
        mean = mlb_hitter_expected_dk_points(stats)
    else:
        raise ValueError(f"DFS_UNSUPPORTED_SPORT:{sport}")
    stddev = float(stats.get("dk_stddev", 0.0) or 0.0)
    if stddev <= 0:
        stddev = max(2.0, sqrt(max(mean, 1.0)) * 1.55)
    ceiling = float(stats.get("dk_ceiling", 0.0) or 0.0) or mean + 1.65 * stddev
    floor = float(stats.get("dk_floor", 0.0) or 0.0) or max(0.0, mean - 1.15 * stddev)
    own = stats.get("ownership")
    return Projection(
        player_id=player.player_id,
        mean=mean,
        ceiling=max(mean, ceiling),
        floor=max(0.0, min(mean, floor)),
        stddev=stddev,
        ownership=float(own) if own is not None else None,
        source=source,
        components={str(k): float(v) for k, v in stats.items() if isinstance(v, (int, float))},
    )


def dk_fppg_baseline(player: DKPlayer, *, source: str = "DK_FPPG_BASELINE") -> Projection:
    if player.dk_fppg is None:
        raise ValueError(f"DFS_MISSING_PROJECTION:{player.name}")
    mean = max(0.0, float(player.dk_fppg))
    stddev = max(2.0, sqrt(max(mean, 1.0)) * 1.65)
    return Projection(
        player_id=player.player_id,
        mean=mean,
        ceiling=mean + 1.65 * stddev,
        floor=max(0.0, mean - 1.15 * stddev),
        stddev=stddev,
        source=source,
    )
