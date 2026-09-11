from __future__ import annotations

import pytest

from sportsedge.mlb_v7_final_timecode import latest_confirmed_final_rows
from sportsedge.mlb_v7_statsapi_history import MLBV7StatsAPIHistoryError


def _game():
    return {
        "game_id": 1,
        "away_team_id": 10,
        "home_team_id": 20,
        "venue_id": 15,
        "game_start_time": "2023-01-10T18:00:00+00:00",
        "status": "Final",
        "official_date": "2023-01-10",
        "game_type": "R",
    }


def _snapshot(status: str):
    return {"gameData": {"status": {"abstractGameState": status}}}


def test_scans_backward_past_nonfinal_timestamp_tail():
    codes = ["20230110_210000", "20230110_210100"]
    states = {codes[0]: "Final", codes[1]: "Live"}
    rows, selected, snapshot = latest_confirmed_final_rows(
        _game(), codes, lambda code: _snapshot(states[code])
    )
    assert selected == codes[0]
    assert len(rows) == 2
    assert all(row.final_at_semantics == "LATEST_HISTORICAL_TIMECODE_CONFIRMED_FINAL" for row in rows)
    assert snapshot["gameData"]["status"]["abstractGameState"] == "Final"


def test_uses_last_timestamp_when_it_is_final():
    codes = ["20230110_205900", "20230110_210000"]
    rows, selected, _ = latest_confirmed_final_rows(_game(), codes, lambda code: _snapshot("Final"))
    assert selected == codes[-1]
    assert len(rows) == 2


def test_blocks_when_no_timestamp_confirms_final():
    with pytest.raises(MLBV7StatsAPIHistoryError, match="NO_HISTORICAL_TIMECODE_CONFIRMED_FINAL"):
        latest_confirmed_final_rows(_game(), ["20230110_210100"], lambda code: _snapshot("Live"))
