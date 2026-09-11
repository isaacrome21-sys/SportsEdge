from __future__ import annotations
from copy import deepcopy

import pytest

from sportsedge.mlb_v7_bullpen_park_sources import MLBV7RawSourceError, bullpen_usage_rows, park_raw_rows


def _pitcher(pid: int, *, starter: bool, pitches: int):
    return {
        "person": {"id": pid},
        "stats": {"pitching": {
            "gamesStarted": 1 if starter else 0,
            "gamesPitched": 1,
            "numberOfPitches": pitches,
            "pitchesThrown": pitches,
        }},
    }


def feed():
    return {
        "gamePk": 123,
        "metaData": {
            "timeStamp": "20230402_210000",
            "gameEvents": ["field_out", "game_finished"],
            "logicalEvents": ["gameStateChangeToGameOver"],
        },
        "gameData": {
            "status": {"abstractGameState": "Final"},
            "game": {"season": "2023", "type": "R"},
            "datetime": {"dateTime": "2023-04-02T18:00:00Z", "officialDate": "2023-04-02"},
            "teams": {"away": {"id": 10}, "home": {"id": 20}},
            "venue": {"id": 15},
        },
        "liveData": {
            "boxscore": {"teams": {
                "away": {
                    "team": {"id": 10}, "pitchers": [101, 102],
                    "players": {"ID101": _pitcher(101, starter=True, pitches=80), "ID102": _pitcher(102, starter=False, pitches=20)},
                },
                "home": {
                    "team": {"id": 20}, "pitchers": [201, 202, 203],
                    "players": {
                        "ID201": _pitcher(201, starter=True, pitches=70),
                        "ID202": _pitcher(202, starter=False, pitches=15),
                        "ID203": _pitcher(203, starter=False, pitches=12),
                    },
                },
            }},
            "plays": {"allPlays": [
                {"matchup": {"batSide": {"code": "L"}}, "result": {"awayScore": 0, "homeScore": 0, "eventType": "strikeout"}},
                {"matchup": {"batSide": {"code": "R"}}, "result": {"awayScore": 1, "homeScore": 0, "eventType": "home_run"}},
                {"matchup": {"batSide": {"code": "L"}}, "result": {"awayScore": 1, "homeScore": 2, "eventType": "double"}},
            ]},
            "linescore": {"teams": {"away": {"runs": 1}, "home": {"runs": 2}}},
        },
    }


def test_bullpen_excludes_exact_starters_and_keeps_pitch_counts():
    rows = bullpen_usage_rows(feed())
    assert [(r.team_id, r.pitcher_id, r.pitches) for r in rows] == [(10, 102, 20), (20, 202, 15), (20, 203, 12)]
    assert all(r.final_at == "2023-04-02T21:00:00+00:00" for r in rows)


def test_bullpen_blocks_pitch_count_disagreement():
    f = feed()
    f["liveData"]["boxscore"]["teams"]["away"]["players"]["ID102"]["stats"]["pitching"]["pitchesThrown"] = 19
    with pytest.raises(MLBV7RawSourceError, match="PITCH_COUNT_MISMATCH"):
        bullpen_usage_rows(f)


def test_bullpen_blocks_ambiguous_starter_cardinality():
    f = feed()
    f["liveData"]["boxscore"]["teams"]["away"]["players"]["ID102"]["stats"]["pitching"]["gamesStarted"] = 1
    with pytest.raises(MLBV7RawSourceError, match="STARTER_CARDINALITY_INVALID"):
        bullpen_usage_rows(f)


def test_park_rows_are_plate_appearance_level_and_reconcile_runs():
    rows = park_raw_rows(feed())
    assert len(rows) == 3
    assert [r.batter_stand for r in rows] == ["L", "R", "L"]
    assert [r.runs for r in rows] == [0, 1, 2]
    assert [r.home_runs for r in rows] == [0, 1, 0]
    assert sum(r.plate_appearances for r in rows) == 3
    assert sum(r.runs for r in rows) == 3


def test_park_uses_actual_matchup_stand_and_blocks_unknown():
    f = feed()
    f["liveData"]["plays"]["allPlays"][0]["matchup"]["batSide"]["code"] = "S"
    with pytest.raises(MLBV7RawSourceError, match="BATTER_STAND_INVALID"):
        park_raw_rows(f)


def test_park_blocks_score_regression():
    f = feed()
    f["liveData"]["plays"]["allPlays"][2]["result"]["awayScore"] = 0
    with pytest.raises(MLBV7RawSourceError, match="SCORE_REGRESSION"):
        park_raw_rows(f)


def test_both_sources_require_explicit_game_finished_evidence():
    f = feed()
    f["metaData"]["gameEvents"] = []
    with pytest.raises(MLBV7RawSourceError, match="ARCHIVED_FEED_GAME_FINISHED_EVENT_MISSING"):
        bullpen_usage_rows(f)
    with pytest.raises(MLBV7RawSourceError, match="ARCHIVED_FEED_GAME_FINISHED_EVENT_MISSING"):
        park_raw_rows(f)
