"""Regression probes for malformed offline MLB starter evidence inputs.

No network calls, capture activation, archived collectors, or real clocks.
"""
from sportsedge.sports.mlb.starter_capture import parse_schedule_games, detect_changes


def test_malformed_schedule_containers_refuse_without_crash():
    for value in (None, [], 8, "bad", {"dates": None}, {"dates": [3, None, {"games": 2}]}):
        assert parse_schedule_games(value) == []


def test_malformed_nested_team_and_status_are_not_bound():
    rows = parse_schedule_games({
        "dates": [{"games": [{
            "gamePk": 123, "gameType": "R",
            "gameDate": "2026-10-13T20:00:00Z",
            "teams": {"away": [], "home": {"team": "not-a-team"}},
            "status": [],
        }]}]
    })
    assert len(rows) == 1
    assert rows[0]["away_team_id"] is None
    assert rows[0]["home_team_id"] is None


def test_bad_snapshot_identity_cannot_crash_change_derivation():
    stream = [
        {"record_type": "SNAPSHOT", "game_date_utc": "2026-10-13T20:00:00Z", "game_pk": "abc"},
        {"record_type": "SNAPSHOT", "game_date_utc": "2026-10-13T20:00:00Z", "game_pk": []},
        [],
        None,
    ]
    assert detect_changes(stream) == []
