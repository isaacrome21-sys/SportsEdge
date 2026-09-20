"""Fail-closed NFL probability read-outs from existing shared simulation paths.

These functions create probability mechanics only. They do not confer promotion,
Truth-Gate, staking, eligibility, or OFFICIAL authority.
"""
from __future__ import annotations

from collections.abc import Iterable

from .usage import AttributedFootballPath
from .player_markets import _paths, _player_profile


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
        counts.append(float(row["rushing_tds"]) + float(row["receiving_tds"]))
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
