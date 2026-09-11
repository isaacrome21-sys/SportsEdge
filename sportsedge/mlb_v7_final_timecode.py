from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from .mlb_v7_statsapi_history import MLBV7StatsAPIHistoryError
from .mlb_v7_travel_history import HistoricalGameRow, normalize_final_game, snapshot_status


def _with_semantics(rows: list[HistoricalGameRow], semantics: str) -> list[HistoricalGameRow]:
    return [replace(row, final_at_semantics=semantics) for row in rows]


def archived_final_feed_rows(
    game: dict[str, Any],
    feed_payload: Any,
) -> tuple[list[HistoricalGameRow], str]:
    """Use MLB's archived full feed only when it explicitly proves game-over.

    This fallback is intentionally stricter than checking status alone. The feed
    must be Final, carry the game-finished event, carry the logical transition to
    game over, and expose its native metadata timeStamp. That timestamp becomes
    final_at and the raw feed must be hash-bound by the caller.
    """
    if snapshot_status(feed_payload) != "Final":
        raise MLBV7StatsAPIHistoryError("ARCHIVED_FEED_NOT_FINAL")
    if not isinstance(feed_payload, dict):
        raise MLBV7StatsAPIHistoryError("ARCHIVED_FEED_INVALID")
    meta = feed_payload.get("metaData") or {}
    if not isinstance(meta, dict):
        raise MLBV7StatsAPIHistoryError("ARCHIVED_FEED_METADATA_MISSING")
    game_events = meta.get("gameEvents")
    logical_events = meta.get("logicalEvents")
    if not isinstance(game_events, list) or "game_finished" not in game_events:
        raise MLBV7StatsAPIHistoryError("ARCHIVED_FEED_GAME_FINISHED_EVENT_MISSING")
    if not isinstance(logical_events, list) or "gameStateChangeToGameOver" not in logical_events:
        raise MLBV7StatsAPIHistoryError("ARCHIVED_FEED_GAME_OVER_TRANSITION_MISSING")
    timecode = meta.get("timeStamp")
    if not isinstance(timecode, str) or not timecode:
        raise MLBV7StatsAPIHistoryError("ARCHIVED_FEED_TIMESTAMP_MISSING")
    rows = normalize_final_game(game, {"timestamps": [timecode]}, feed_payload)
    return _with_semantics(rows, "ARCHIVED_FULL_FEED_GAME_FINISHED_METADATA_TIMESTAMP"), timecode


def latest_confirmed_final_rows(
    game: dict[str, Any],
    timecodes: list[str],
    fetch_snapshot: Callable[[str], Any],
) -> tuple[list[HistoricalGameRow], str, Any]:
    """Return rows at the latest historical timecode whose snapshot confirms Final."""
    if not timecodes:
        raise MLBV7StatsAPIHistoryError("FINAL_GAME_TIMESTAMPS_MISSING")
    for index in range(len(timecodes) - 1, -1, -1):
        timecode = timecodes[index]
        snapshot = fetch_snapshot(timecode)
        if snapshot_status(snapshot) != "Final":
            continue
        trimmed = {"timestamps": timecodes[: index + 1]}
        rows = normalize_final_game(game, trimmed, snapshot)
        return _with_semantics(rows, "LATEST_HISTORICAL_TIMECODE_CONFIRMED_FINAL"), timecode, snapshot
    raise MLBV7StatsAPIHistoryError("NO_HISTORICAL_TIMECODE_CONFIRMED_FINAL")
