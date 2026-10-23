"""Week-clustered paired bootstrap for research screens (no data, no quotes).

Games in the same (season, week) share league-wide conditions, so resampling
individual games understates uncertainty. This resamples whole weeks with
replacement and returns a percentile interval for the mean paired delta.
"""
from __future__ import annotations

import math
import random
from typing import Hashable, Sequence


class ClusterBootstrapError(ValueError):
    pass


def week_key(game_id: str) -> str:
    """'2024_07_BUF_KC' -> '2024_07'; refuses anything else."""
    if not isinstance(game_id, str):
        raise ClusterBootstrapError("GAME_ID_REQUIRED")
    parts = game_id.split("_")
    if len(parts) < 4 or len(parts[0]) != 4 or not parts[0].isdigit() \
            or len(parts[1]) != 2 or not parts[1].isdigit():
        raise ClusterBootstrapError(f"GAME_ID_MALFORMED:{game_id}")
    return f"{parts[0]}_{parts[1]}"


def cluster_ci(deltas: Sequence[float], clusters: Sequence[Hashable], *, alpha: float,
               reps: int = 2000, seed: int = 20261023) -> tuple[float, float, int]:
    """Return (lo, hi, n_clusters) for the mean delta, resampling clusters."""
    if len(deltas) != len(clusters) or not deltas:
        raise ClusterBootstrapError("LENGTH_MISMATCH_OR_EMPTY")
    if not (0 < alpha < 1) or isinstance(reps, bool) or not isinstance(reps, int) or reps < 100:
        raise ClusterBootstrapError("BAD_ALPHA_OR_REPS")
    groups: dict = {}
    for d, c in zip(deltas, clusters):
        if isinstance(d, bool) or not isinstance(d, (int, float)) or not math.isfinite(d):
            raise ClusterBootstrapError("NON_FINITE_DELTA")
        s = groups.setdefault(c, [0.0, 0])
        s[0] += d; s[1] += 1
    keys = sorted(groups, key=repr)
    if len(keys) < 2:
        raise ClusterBootstrapError("TOO_FEW_CLUSTERS")
    rng = random.Random(seed)
    stats = []
    for _ in range(reps):
        tot = n = 0.0
        for _ in keys:
            g = groups[keys[rng.randrange(len(keys))]]
            tot += g[0]; n += g[1]
        stats.append(tot / n)
    stats.sort()
    return stats[int(reps * alpha / 2)], stats[int(reps * (1 - alpha / 2)) - 1], len(keys)
