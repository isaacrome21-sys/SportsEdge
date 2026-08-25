"""Neutral-site policy wrapper for the NFL production-M2 history builder.

Neutral-site games are valuable prior-state observations but cannot be priced
with home-team stadium geography when the exact venue is unresolved.  The
production evidence policy therefore supports two explicit modes:

``error``
    Preserve the underlying fail-closed behavior and reject an unresolved
    neutral venue.

``exclude_from_evaluation``
    Let the game update future EPA/QB/pressure state, but remove its own
    evaluation row.  The underlying builder is called with a temporary
    home-location marker only so it can advance state; any geography calculated
    for that discarded row is never emitted or used by later state updates.

This wrapper exists rather than weakening the core builder's default contract.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .m2_history_features import build_nfl_m2_history_rows as _build_core_history_rows

_ALLOWED_POLICIES = {"error", "exclude_from_evaluation"}


def build_nfl_m2_history_rows(
    schedule_rows: Iterable[Mapping[str, Any]],
    pbp_rows: Iterable[Mapping[str, Any]],
    participation_rows: Iterable[Mapping[str, Any]],
    depth_rows: Iterable[Mapping[str, Any]],
    stadium_rows: Iterable[Mapping[str, Any]],
    *,
    prior_decay_curves: Mapping[int, Mapping[int, float]],
    neutral_site_policy: str = "error",
) -> list[dict[str, Any]]:
    """Build production-M2 rows under an explicit neutral-site policy."""
    policy = str(neutral_site_policy).strip().lower()
    if policy not in _ALLOWED_POLICIES:
        raise ValueError(f"NFL_NEUTRAL_SITE_POLICY_INVALID:{neutral_site_policy}")

    schedule = [dict(row) for row in schedule_rows]
    if policy == "error":
        return _build_core_history_rows(
            schedule,
            pbp_rows,
            participation_rows,
            depth_rows,
            stadium_rows,
            prior_decay_curves=prior_decay_curves,
        )

    excluded_ids: set[str] = set()
    state_schedule: list[dict[str, Any]] = []
    for raw in schedule:
        row = dict(raw)
        location = str(row.get("location") or "Home").strip().lower()
        if location != "home":
            game_id = str(row.get("game_id") or "").strip()
            if not game_id:
                raise ValueError("NFL_HISTORY_GAME_IDENTITY_MISSING")
            excluded_ids.add(game_id)
            # The core builder requires a resolvable venue to construct a row.
            # This row is discarded below; state updates are PBP/QB based and do
            # not depend on the temporary venue marker.
            row["location"] = "Home"
        state_schedule.append(row)

    built = _build_core_history_rows(
        state_schedule,
        pbp_rows,
        participation_rows,
        depth_rows,
        stadium_rows,
        prior_decay_curves=prior_decay_curves,
    )
    return [row for row in built if str(row.get("game_id") or "") not in excluded_ids]
