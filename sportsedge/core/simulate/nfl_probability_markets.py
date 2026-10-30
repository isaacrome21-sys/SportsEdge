"""Fail-closed NFL probability read-outs from existing shared simulation paths.

These functions create probability mechanics only. They do not confer promotion,
Truth-Gate, staking, eligibility, or OFFICIAL authority.
"""
from __future__ import annotations

from collections.abc import Iterable
from math import isfinite
from numbers import Real

import numpy as np

from .usage import AttributedFootballPath
from .player_markets import _paths, _player_profile
from .nfl_possession_challenger import VectorizedSummary, VectorizedPossessionChallengerBaseline


def _offensive_touchdown_counts(
    paths: Iterable[AttributedFootballPath], *, player_id: str
) -> list[float]:
    """Return offensive TD counts after one shared participation/identity check."""
    materialized = _paths(paths)
    player = str(player_id).strip()
    if not player:
        raise ValueError("PLAYER_ID_REQUIRED")

    profiles = [_player_profile(path, player) for path in materialized]
    identity = {(profile.team, profile.position) for profile in profiles}
    if len(identity) != 1:
        raise ValueError("PLAYER_USAGE_IDENTITY_MISMATCH")
    if any(profile.active is None for profile in profiles):
        raise ValueError(f"PARTICIPATION_UNRESOLVED:{player}")
    if any(profile.active is not True for profile in profiles):
        raise ValueError(f"PLAYER_INACTIVE:{player}")

    counts: list[float] = []
    for path in materialized:
        stats = path.player_stats()
        if player not in stats:
            raise ValueError(f"PLAYER_STATS_MISSING:{player}")
        row = stats[player]
        # Offensive player-TD settlement: rushing + receiving TDs. Passing TDs
        # do not make the quarterback a scorer and return TDs remain separate.
        if "rushing_tds" not in row or "receiving_tds" not in row:
            raise ValueError("PLAYER_TD_COMPONENTS_MISSING")
        components = [row["rushing_tds"], row["receiving_tds"]]
        if any(
            isinstance(value, (bool, np.bool_)) or not isinstance(value, Real)
            or not isfinite(value) or value < 0 or float(value) != int(value)
            for value in components
        ):
            raise ValueError("PLAYER_TD_COUNT_INVALID")
        counts.append(sum(int(value) for value in components))
    return counts


def derive_anytime_touchdown_probability(
    paths: Iterable[AttributedFootballPath], *, player_id: str
) -> dict[str, float]:
    """Return P(player scores >=1 offensive TD) from the shared attributed paths."""
    counts = _offensive_touchdown_counts(paths, player_id=player_id)
    p = sum(value >= 1.0 for value in counts) / float(len(counts))
    return {"yes": p, "no": 1.0 - p}


def derive_two_plus_touchdown_probability(
    paths: Iterable[AttributedFootballPath], *, player_id: str
) -> dict[str, float]:
    """Return P(player scores >=2 offensive TDs) from the same shared TD counts.

    This is a probability read-out only. It deliberately reuses the ATTD scorer
    identity/participation contract so two-plus cannot drift onto an independent
    Bernoulli approximation or count quarterback passing TDs.
    """
    counts = _offensive_touchdown_counts(paths, player_id=player_id)
    p = sum(value >= 2.0 for value in counts) / float(len(counts))
    return {"yes": p, "no": 1.0 - p}


def derive_safety_probability(summary: VectorizedSummary) -> dict[str, float]:
    """Return P(at least one safety) from the possession challenger's parent paths.

    The summary must retain per-path outcome counts. This is a challenger-only
    structural read-out and carries no production or promotion authority.
    """
    counts = summary.outcome_counts
    expected = len(VectorizedPossessionChallengerBaseline.OUTCOMES)
    if getattr(counts, "ndim", None) != 2 or counts.shape[1] != expected:
        raise ValueError("CHALLENGER_OUTCOME_COUNT_SHAPE_INVALID")
    if len(counts) == 0:
        raise ValueError("SIMULATION_ROWS_EMPTY")
    if counts.dtype.kind not in "iuf" or not np.all(np.isfinite(counts)):
        raise ValueError("CHALLENGER_OUTCOME_COUNT_INVALID")
    if np.any(counts < 0) or np.any(counts != np.floor(counts)):
        raise ValueError("CHALLENGER_OUTCOME_COUNT_INVALID")
    for values in (summary.margins, summary.totals, summary.home_possessions,
                   summary.away_possessions, summary.overtime_possessions):
        if getattr(values, "shape", None) != (len(counts),):
            raise ValueError("CHALLENGER_SUMMARY_ROW_MISMATCH")
    safety_index = list(VectorizedPossessionChallengerBaseline.OUTCOMES).index("SAFETY")
    yes = sum(int(value) > 0 for value in counts[:, safety_index]) / float(len(counts))
    return {"yes": yes, "no": 1.0 - yes}
