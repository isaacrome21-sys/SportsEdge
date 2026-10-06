"""Research adapter for building the pitcher-K workload candidate from MLB history.

Kept outside frozen production model-surface files. The supplied history source is
responsible for returning strictly-prior pitching game-log rows.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from .mlb_pitcher_k_workload_candidate import (
    PitcherKWorkloadCandidateError,
    build_workload_bundle,
)


class PitcherKWorkloadSourceError(ValueError):
    pass


def _is_start(row: Mapping[str, Any]) -> bool:
    stat = row.get("stat")
    if not isinstance(stat, Mapping):
        return False
    try:
        value = float(stat.get("gamesStarted", 0))
    except (TypeError, ValueError):
        return False
    return value >= 1


def build_from_history_source(source, *, player_id: int, target_date: date) -> dict[str, Any]:
    """Build the research bundle from the source's existing cached pitching rows."""
    try:
        rows = source.player_rows(
            player_id=int(player_id),
            group="pitching",
            target_date=target_date,
        )
    except Exception as exc:
        raise PitcherKWorkloadSourceError(f"HISTORY_SOURCE_FAILED:{type(exc).__name__}") from exc

    starts = [row for row in rows if isinstance(row, Mapping) and _is_start(row)][-10:]
    try:
        return build_workload_bundle(starts)
    except PitcherKWorkloadCandidateError as exc:
        raise PitcherKWorkloadSourceError(f"WORKLOAD_BUNDLE_BLOCKED:{exc}") from exc
