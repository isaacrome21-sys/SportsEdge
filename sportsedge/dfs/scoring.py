from __future__ import annotations

from math import sqrt
from statistics import fmean, pstdev
from typing import Iterable, Mapping

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


def _football_sample_stats(player: DKPlayer, sample: Mapping[str, float]) -> dict[str, float]:
    out = {str(k): float(v) for k, v in sample.items() if isinstance(v, (int, float))}
    aliases = {
        "passing_yards": "pass_yards",
        "passing_tds": "pass_tds",
        "rushing_yards": "rush_yards",
        "rushing_tds": "rush_tds",
        "receiving_yards": "rec_yards",
        "receiving_tds": "rec_tds",
    }
    for src, dst in aliases.items():
        if src in out and dst not in out:
            out[dst] = out[src]
    pos = set(player.positions)
    if "QB" in pos:
        required = {"pass_yards", "pass_tds", "interceptions", "rush_yards", "rush_tds"}
    elif pos & {"RB", "WR", "TE"}:
        required = {"receptions", "rec_yards", "rec_tds", "rush_yards", "rush_tds"}
    else:
        raise ValueError(f"DFS_SAMPLE_POSITION_UNSUPPORTED:{player.name}:{player.positions}")
    missing = sorted(required - set(out))
    if missing:
        raise ValueError(f"DFS_SAMPLE_COMPONENTS_MISSING:{player.player_id}:{','.join(missing)}")
    out["p_pass_300"] = float(out.get("pass_yards", 0.0) >= 300.0)
    out["p_rush_100"] = float(out.get("rush_yards", 0.0) >= 100.0)
    out["p_rec_100"] = float(out.get("rec_yards", 0.0) >= 100.0)
    return out


def _mlb_sample_stats(player: DKPlayer, sample: Mapping[str, float]) -> dict[str, float]:
    out = {str(k): float(v) for k, v in sample.items() if isinstance(v, (int, float))}
    if "P" in player.positions:
        required = {"outs", "strikeouts", "earned_runs", "hits_allowed", "walks_allowed"}
    else:
        required = {"singles", "doubles", "triples", "home_runs", "rbi", "runs", "walks", "hbp", "stolen_bases"}
    missing = sorted(required - set(out))
    if missing:
        raise ValueError(f"DFS_SAMPLE_COMPONENTS_MISSING:{player.player_id}:{','.join(missing)}")
    return out


def projection_from_samples(
    player: DKPlayer,
    sport: str,
    samples: Iterable[Mapping[str, float]],
    *,
    source: str,
    ownership: float | None = None,
) -> Projection:
    """Convert complete SportsEdge outcome paths into a DFS score distribution.

    Partial Stage-3 distributions intentionally fail closed until TD/event/run layers
    have augmented them with every component needed by DraftKings scoring.
    """
    scores: list[float] = []
    for sample in samples:
        if "dk_points" in sample:
            scores.append(float(sample["dk_points"]))
            continue
        if sport.upper() in {"NFL", "CFB"}:
            scores.append(football_expected_dk_points(_football_sample_stats(player, sample)))
        elif sport.upper() == "MLB" and "P" in player.positions:
            scores.append(mlb_pitcher_expected_dk_points(_mlb_sample_stats(player, sample)))
        elif sport.upper() == "MLB":
            scores.append(mlb_hitter_expected_dk_points(_mlb_sample_stats(player, sample)))
        else:
            raise ValueError(f"DFS_UNSUPPORTED_SPORT:{sport}")
    if len(scores) < 1000:
        raise ValueError(f"DFS_TOO_FEW_PLAYER_PATHS:{player.player_id}:{len(scores)}")
    scores.sort()

    def quantile(q: float) -> float:
        idx = min(len(scores) - 1, max(0, int(round((len(scores) - 1) * q))))
        return scores[idx]

    mean = fmean(scores)
    return Projection(
        player_id=player.player_id,
        mean=mean,
        ceiling=max(mean, quantile(0.95)),
        floor=max(0.0, min(mean, quantile(0.10))),
        stddev=pstdev(scores),
        ownership=ownership,
        source=source,
        components={"simulation_paths": float(len(scores))},
    )
