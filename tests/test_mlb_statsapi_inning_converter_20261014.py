"""Synthetic StatsAPI-shaped feed tests, not sourced MLB results."""
import pytest

from sportsedge.mlb_statsapi_inning_converter import (
    convert_final_game_feed, make_historical_export,
)


def _feed(pk=123):
    return {
        "gameData": {"game": {"pk": pk}, "status": {"abstractGameState": "Final"},
                     "datetime": {"dateTime": "2026-08-01T18:00:00Z"}},
        "liveData": {"linescore": {
            "innings": [
                {"num": i, "away": {"runs": 0}, "home": {"runs": 1 if i == 1 else 0}}
                for i in range(1, 10)
            ],
            "teams": {"home": {"runs": 1}, "away": {"runs": 0}},
        }},
    }


def test_complete_final_feed():
    row = convert_final_game_feed(_feed())
    assert row["game_id"] == "123"
    assert row["inning_runs"] == [1] + [0] * 8


def test_unplayed_bottom_ninth_requires_home_lead():
    feed = _feed()
    feed["liveData"]["linescore"]["innings"][-1]["home"]["runs"] = None
    assert convert_final_game_feed(feed)["inning_runs"][-1] == 0
    feed["liveData"]["linescore"]["teams"]["home"]["runs"] = 0
    with pytest.raises(ValueError, match="UNVERIFIED_UNPLAYED_HOME_HALF"):
        convert_final_game_feed(feed)


def test_not_final_refused():
    feed = _feed()
    feed["gameData"]["status"]["abstractGameState"] = "Live"
    with pytest.raises(ValueError, match="GAME_NOT_FINAL"):
        convert_final_game_feed(feed)


def test_score_mismatch_refused():
    feed = _feed()
    feed["liveData"]["linescore"]["teams"]["away"]["runs"] = 2
    with pytest.raises(ValueError, match="INNING_TOTAL_MISMATCH"):
        convert_final_game_feed(feed)


def test_duplicate_ids_refused():
    with pytest.raises(ValueError, match="DUPLICATE_GAME_ID"):
        make_historical_export([_feed(), _feed()],
                               source_url="https://statsapi.mlb.com/api/v1.1/game/feed/live",
                               observed_at="2026-10-01T00:00:00Z")


def test_valid_export_is_research_only():
    payload = make_historical_export(
        [_feed()], source_url="https://statsapi.mlb.com/api/v1.1/game/feed/live",
        observed_at="2026-10-01T00:00:00Z")
    assert payload["schema"] == "MLB_HISTORICAL_INNING_EXPORT_V1"
    assert len(payload["games"]) == 1
    assert "play_authorized" not in payload
