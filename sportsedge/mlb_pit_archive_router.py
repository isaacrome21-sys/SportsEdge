"""Canonical PIT archive dispatcher for MLB evidence joins.

The count-prop and additional-market archives intentionally keep different provider
identity contracts, but callers should not need to guess which joiner owns a saved
artifact. Dispatch is by immutable archive_type only and unknown types fail closed.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from .mlb_additional_pit_joiner import ARCHIVE_TYPE as ADDITIONAL_ARCHIVE_TYPE, join_additional_archive
from .mlb_pit_joiner import MLBPITJoinError, join_prop_archive

COUNT_ARCHIVE_TYPE = "MLB_PROP_PIT_QUOTES"
SUPPORTED_ARCHIVE_TYPES = frozenset({COUNT_ARCHIVE_TYPE, ADDITIONAL_ARCHIVE_TYPE})


def join_mlb_pit_archive(
    *,
    archive_payload: Mapping[str, Any],
    game_candidates: Iterable[Mapping[str, Any]],
    player_candidates_by_game: Mapping[str, Iterable[Mapping[str, Any]]],
    model_rows: Iterable[Mapping[str, Any]],
    official_fact_reports: Iterable[Mapping[str, Any]],
    settlement_rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    archive_type = str(archive_payload.get("archive_type") or "").strip()
    kwargs = dict(
        archive_payload=archive_payload,
        game_candidates=game_candidates,
        player_candidates_by_game=player_candidates_by_game,
        model_rows=model_rows,
        official_fact_reports=official_fact_reports,
        settlement_rows=settlement_rows,
    )
    if archive_type == COUNT_ARCHIVE_TYPE:
        return join_prop_archive(**kwargs)
    if archive_type == ADDITIONAL_ARCHIVE_TYPE:
        return join_additional_archive(**kwargs)
    raise MLBPITJoinError(f"PIT_ARCHIVE_TYPE_UNSUPPORTED:{archive_type or 'MISSING'}")
