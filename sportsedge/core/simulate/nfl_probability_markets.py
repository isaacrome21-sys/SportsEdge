"""Fail-closed NFL probability read-outs from existing shared simulation paths.

These functions create probability mechanics only. They do not confer promotion,
Truth-Gate, staking, eligibility, or OFFICIAL authority.
"""
from __future__ import annotations

from collections.abc import Iterable

from .usage import AttributedFootballPath
from .player_markets import _paths, _player_profile


def derive_anytime_touchdown_probability(
    paths: Iterable[AttributedFootballPath], *, player_id: str
) -> dict[str, float]:
    """Return P(player scores >=1 offensive TD) from the shared attributed paths.

    TD identity comes from the same path that produces rushing/receiving stats,
    preserving teammate/opportunity correlation already present in that path.
    Unknown/inactive participation fails closed. Return-score TD identity is not
    silently added; that remains a separate blocked surface.
    """
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

    scored = 0
    for path in materialized:
        stats = path.player_stats()
        if player not in stats:
            raise ValueError(f"PLAYER_STATS_MISSING:{player}")
        row = stats[player]
        # Offensive anytime-TD settlement: rushing + receiving TDs. Passing TDs
        # do not make the quarterback an anytime-TD scorer.
        if "rushing_tds" not in row or "receiving_tds" not in row:
            raise ValueError("PLAYER_TD_COMPONENTS_MISSING")
        td_count = float(row["rushing_tds"]) + float(row["receiving_tds"])
        scored += td_count >= 1.0

    p = scored / float(len(materialized))
    return {"yes": p, "no": 1.0 - p}
