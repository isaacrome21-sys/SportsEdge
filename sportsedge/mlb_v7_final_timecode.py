from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from .mlb_v7_statsapi_history import MLBV7StatsAPIHistoryError
from .mlb_v7_travel_history import HistoricalGameRow, normalize_final_game, snapshot_status


def latest_confirmed_final_rows(
    game: dict[str, Any],
    timecodes: list[str],
    fetch_snapshot: Callable[[str], Any],
) -> tuple[list[HistoricalGameRow], str, Any]:
    """Return rows at the latest historical timecode whose snapshot confirms Final.

    MLB can append historical timecodes whose snapshot no longer reports Final.
    Scanning backward keeps the derivation conservative: a game only enters history
    after an authentic historical snapshot explicitly confirms Final.
    """
    if not timecodes:
        raise MLBV7StatsAPIHistoryError("FINAL_GAME_TIMESTAMPS_MISSING")
    for index in range(len(timecodes) - 1, -1, -1):
        timecode = timecodes[index]
        snapshot = fetch_snapshot(timecode)
        if snapshot_status(snapshot) != "Final":
            continue
        trimmed = {"timestamps": timecodes[: index + 1]}
        rows = normalize_final_game(game, trimmed, snapshot)
        rows = [
            replace(row, final_at_semantics="LATEST_HISTORICAL_TIMECODE_CONFIRMED_FINAL")
            for row in rows
        ]
        return rows, timecode, snapshot
    raise MLBV7StatsAPIHistoryError("NO_HISTORICAL_TIMECODE_CONFIRMED_FINAL")
