"""Bind PIT-safe NFL qualification snapshots to locked Score rule B.

Design reference: the user-supplied MySpariEdge NFL Props Edge Model, NFL Prop
Picks Model, Touchdown Picks Model and Game Picks Model materials separate
model/role/context quality from sportsbook economics. This adapter implements
that disclosed separation without copying hidden formulas or weights.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from sportsedge.nfl_run_it_qualification import qualification_flags_from_snapshot
from sportsedge.nfl_run_it_scoring import qualification_role_score


class NflRunItScoreBindingError(ValueError):
    pass


def _identity(row: Mapping[str, Any]) -> tuple[str, str, str]:
    values = tuple(str(row.get(k) or "").strip() for k in ("game_id", "market", "selection"))
    if not all(values):
        raise NflRunItScoreBindingError("QUALIFICATION_IDENTITY_INCOMPLETE")
    return values


def score_b_by_identity(snapshots: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str, str], int]:
    """Return deterministic Score-B values keyed by game/market/selection.

    Duplicate identities are allowed only when they resolve to identical flags;
    disagreement fails closed rather than silently selecting a snapshot.
    """
    out: dict[tuple[str, str, str], int] = {}
    seen_flags: dict[tuple[str, str, str], dict[str, bool]] = {}
    for snapshot in snapshots:
        if not isinstance(snapshot, Mapping):
            raise NflRunItScoreBindingError("QUALIFICATION_SNAPSHOT_REQUIRED")
        key = _identity(snapshot)
        flags = qualification_flags_from_snapshot(snapshot)
        prior = seen_flags.get(key)
        if prior is not None and prior != flags:
            raise NflRunItScoreBindingError("CONFLICTING_QUALIFICATION_SNAPSHOT")
        seen_flags[key] = flags
        out[key] = qualification_role_score(flags)
    return out


def bind_score_b(rows: Sequence[Mapping[str, Any]], snapshots: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Attach Score B to bettor-facing rows without changing their economics/order.

    Every output row requires an exact qualification identity. Sportsbook price,
    EV and edge stay untouched and are never passed into score construction.
    """
    scores = score_b_by_identity(snapshots)
    bound: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise NflRunItScoreBindingError("RUN_IT_ROW_REQUIRED")
        key = _identity(row)
        if key not in scores:
            raise NflRunItScoreBindingError("QUALIFICATION_SNAPSHOT_REQUIRED_FOR_ROW")
        item = dict(row)
        item["score_0_100"] = scores[key]
        bound.append(item)
    return bound
