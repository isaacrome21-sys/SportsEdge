from datetime import datetime, timedelta, timezone
from sportsedge.research.nba_sides_elo_v2 import project_sides


def history():
    d = datetime(2026, 8, 1, tzinfo=timezone.utc)
    return [{
        "game_id": str(i), "tipoff": (d+timedelta(days=i)).isoformat(),
        "observed_at": (d+timedelta(days=i, hours=4)).isoformat(),
        "source_ref": "finals-proof", "home": "A", "away": "B",
        "season": "2026", "home_score": 119, "away_score": 101,
    } for i in range(18)]


def test_elo_sides_project_from_results_only():
    out = project_sides(history(), home="A", away="B",
                        as_of="2026-10-21T18:00:00Z")
    assert out["status"] == "RESEARCH_PROJECTION"
    assert out["projected_home_margin"] > 2.0
    assert out["raw_home_win_probability"] > 0.5
    assert out["price_or_market_used_in_prediction"] is False
    assert out["model_screen"] == "NOT_RUN"


def test_future_game_does_not_leak_even_if_extreme():
    g = history()
    first = project_sides(g, home="A", away="B",
                          as_of="2026-10-21T18:00:00Z")
    g.append({"game_id": "future",
              "tipoff": "2026-10-22T00:00:00Z",
              "observed_at": "2026-10-22T04:00:00Z",
              "source_ref": "source", "home": "A", "away": "B",
              "season": "2026", "home_score": 50, "away_score": 200})
    second = project_sides(g, home="A", away="B",
                           as_of="2026-10-21T18:00:00Z")
    assert first["projected_home_margin"] == second["projected_home_margin"]
    assert second["future_excluded"] == 1


def test_bare_team_history_refuses_not_a_pick():
    out = project_sides(history(), home="A", away="Unknown",
                        as_of="2026-10-21T18:00:00Z")
    assert out["status"] == "REFUSED"
    assert out["reason"] == "NBA_SIDE_INSUFFICIENT_TEAM_GAMES"


def test_missing_verified_result_time_refuses():
    g = history()
    del g[0]["observed_at"]
    try:
        project_sides(g, home="A", away="B",
                      as_of="2026-10-21T18:00:00Z")
    except ValueError as e:
        assert "RESULT_AVAILABLE_INVALID" in str(e)
    else:
        assert False, "no silent inferred availability"
