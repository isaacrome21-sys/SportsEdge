"""Bind PIT-safe NFL qualification snapshots to locked Score rule B."""
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
