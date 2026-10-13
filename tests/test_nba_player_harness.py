from datetime import datetime, timedelta, timezone

from sportsedge.sports.nba.player_harness import (FINAL_BUFFER, _poisson_over, parse_player_box,
                                                  trainable)

T = datetime(2025, 1, 10, 0, 30, tzinfo=timezone.utc)


def test_started_but_not_final_game_is_not_trainable():
    assert not trainable(T - timedelta(hours=2), T)
    assert trainable(T - FINAL_BUFFER, T)


def test_parse_drops_dnp_zero_minutes_and_incomplete():
    d = {"id": "1", "date": "2025-01-10T00:30Z", "completed": True, "teams": [{"team_id": "13", "players": [
        {"id": "a", "dnp": False, "MIN": "30", "PTS": "20", "REB": "5", "AST": "4"},
        {"id": "b", "dnp": True, "MIN": None, "PTS": None, "REB": None, "AST": None},
        {"id": "c", "dnp": False, "MIN": "0", "PTS": "0", "REB": "0", "AST": "0"}]}]}
    logs = parse_player_box(d, {"13": "LAL"})
    assert [l.player_id for l in logs] == ["a"] and logs[0].team == "LAL"
    assert parse_player_box(dict(d, completed=False), {"13": "LAL"}) == []


def test_poisson_over():
    assert abs(_poisson_over(2.0, 2.5) - (1 - 5 * 2.718281828 ** -2)) < 1e-6
