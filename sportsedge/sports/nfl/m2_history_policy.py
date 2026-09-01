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

The wrapper also projects historical depth-chart input to rows that the exact
production starter selector could ever accept.  This is a semantics-preserving
performance boundary: non-QBs and non-rank-one rows are rejected by that
selector in every schema, so copying them for every historical game only adds
quadratic work and cannot change starter identity.

This wrapper exists rather than weakening the core builder's default contract.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .m2_history_features import build_nfl_m2_history_rows as _build_core_history_rows

_ALLOWED_POLICIES = {"error", "exclude_from_evaluation"}


def _rank_one(value: Any) -> bool:
    try:
        return int(float(value)) == 1
    except (TypeError, ValueError):
        return False


def _project_starter_depth_rows(
    depth_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Keep exactly the union of rows the production starter selector can use.

    Timestamped charts require ``dt``, QB position under their accepted aliases,
    and ``pos_rank == 1``.  Historical weekly charts require QB under the exact
    weekly position aliases and ``depth_team`` (falling back to ``pos_rank``
    only when that key is absent) equal to 1.  A row is retained if either
    production branch could accept it; no date/week filtering happens here.
    """
    projected: list[dict[str, Any]] = []
    for raw in depth_rows:
        row = dict(raw)
        timestamped_position = str(
            row.get("pos_abb") or row.get("position") or row.get("depth_position") or ""
        ).upper()
        timestamped_candidate = (
            row.get("dt") not in (None, "")
            and timestamped_position == "QB"
            and _rank_one(row.get("pos_rank"))
        )

        weekly_position = str(row.get("depth_position") or row.get("position") or "").upper()
        weekly_rank = row.get("depth_team", row.get("pos_rank"))
        weekly_candidate = weekly_position == "QB" and _rank_one(weekly_rank)

        if timestamped_candidate or weekly_candidate:
            projected.append(row)
    return projected


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
    depth = _project_starter_depth_rows(depth_rows)
    if policy == "error":
        return _build_core_history_rows(
            schedule,
            pbp_rows,
            participation_rows,
            depth,
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
        depth,
        stadium_rows,
        prior_decay_curves=prior_decay_curves,
    )
    return [row for row in built if str(row.get("game_id") or "") not in excluded_ids]
