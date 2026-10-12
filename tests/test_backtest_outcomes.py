"""Outcome parsing against recorded fixtures. No network: the getter is
injected and returns the recorded ESPN scoreboard JSON."""
import json
from pathlib import Path

import pytest

from sportsedge.backtest.outcomes import (
    OutcomeError, fetch_football_scoreboard, parse_completed_football_games,
    settle_game,
)

FIX = Path(__file__).parent / "fixtures" / "backtest"


def recorded_getter(url):
    for day in ("20240908", "20240909", "20240912"):
        if "dates=" + day in url:
            return json.loads((FIX / ("nfl_scoreboard_%s.json" % day)).read_text())
    raise AssertionError("unexpected URL " + url)


def test_recorded_scoreboard_parses_to_completed_games():
    events = fetch_football_scoreboard("nfl", dates="20240908",
                                       getter=recorded_getter)
    games = parse_completed_football_games(events)
    assert len(games) == 13
    by_id = {g["event_id"]: g for g in games}
    # PIT 18 @ ATL 10 on 2024-09-08 (spot-check a known final)
    pit_atl = next(g for g in games
                   if g["away_team"] == "Pittsburgh Steelers")
    assert pit_atl["away_score"] == 18
    assert pit_atl["home_score"] == 10
    assert all(isinstance(g["home_score"], int) for g in games)
    assert by_id  # event ids unique and present


def test_mnf_and_tnf_days_parse():
    for day, want_away in (("20240909", "New York Jets"),
                           ("20240912", "Buffalo Bills")):
        events = fetch_football_scoreboard("nfl", dates=day,
                                           getter=recorded_getter)
        games = parse_completed_football_games(events)
        assert len(games) == 1
        assert games[0]["away_team"] == want_away


def test_non_completed_games_are_skipped_not_failed():
    events = fetch_football_scoreboard("nfl", dates="20240908",
                                       getter=recorded_getter)
    live = dict(events[0])
    live["status"] = {"type": {"completed": False}}
    games = parse_completed_football_games([live] + events[1:])
    assert len(games) == 12


def test_completed_game_missing_scores_fails_closed():
    events = fetch_football_scoreboard("nfl", dates="20240908",
                                       getter=recorded_getter)
    broken = json.loads(json.dumps(events[0]))
    broken["competitions"][0]["competitors"][0].pop("score", None)
    with pytest.raises(OutcomeError) as exc:
        parse_completed_football_games([broken])
    assert "BACKTEST_HOME_SCORE_UNVERIFIED" in str(exc.value) or \
        "BACKTEST_AWAY_SCORE_UNVERIFIED" in str(exc.value)


def test_settle_game_ml_spread_total():
    game = {"home_score": 24, "away_score": 20}
    assert settle_game(game, "ML", "HOME") == 1.0
    assert settle_game(game, "ML", "AWAY") == 0.0
    assert settle_game(game, "SPREAD", "HOME", line=-3.0) == 1.0   # won by 4
    assert settle_game(game, "SPREAD", "AWAY", line=3.0) == 0.0
    assert settle_game(game, "SPREAD", "HOME", line=-4.0) == 0.5   # push
    assert settle_game(game, "TOTAL", "OVER", line=43.5) == 1.0    # 44 > 43.5
    assert settle_game(game, "TOTAL", "UNDER", line=44.0) == 0.5   # push


def test_settle_game_requires_line_and_rejects_unknown_market():
    game = {"home_score": 24, "away_score": 20}
    with pytest.raises(OutcomeError, match="BACKTEST_LINE_REQUIRED"):
        settle_game(game, "SPREAD", "HOME")
    with pytest.raises(OutcomeError, match="BACKTEST_MARKET_UNSUPPORTED"):
        settle_game(game, "FIRST_TD", "HOME")


def test_unsupported_sport_and_bad_dates_rejected():
    with pytest.raises(OutcomeError, match="BACKTEST_SPORT_UNSUPPORTED"):
        fetch_football_scoreboard("nba", dates="20240908",
                                  getter=recorded_getter)
    with pytest.raises(OutcomeError, match="BACKTEST_DATES_INVALID"):
        fetch_football_scoreboard("nfl", dates="09-08-2024",
                                  getter=recorded_getter)


def test_parse_completed_mlb_games_synthetic():
    from sportsedge.backtest.outcomes import parse_completed_mlb_games
    dates = [{
        "date": "2024-09-08",
        "games": [
            {"gamePk": 777001, "gameDate": "2024-09-08T17:10:00Z",
             "status": {"detailedState": "Final"},
             "teams": {"home": {"team": {"name": "Milwaukee Brewers"}, "score": 5},
                       "away": {"team": {"name": "Los Angeles Dodgers"}, "score": 3}}},
            {"gamePk": 777002, "gameDate": "2024-09-08T18:10:00Z",
             "status": {"detailedState": "Scheduled"},
             "teams": {"home": {"team": {"name": "Chicago Cubs"}, "score": 0},
                       "away": {"team": {"name": "St. Louis Cardinals"}, "score": 0}}},
        ],
    }]
    games = parse_completed_mlb_games(dates)
    assert len(games) == 1  # scheduled game skipped, final parsed
    assert games[0]["event_id"] == "777001"
    assert games[0]["home_score"] == 5
    assert games[0]["away_score"] == 3
    assert settle_game(games[0], "ML", "HOME") == 1.0
    assert settle_game(games[0], "TOTAL", "OVER", line=7.5) == 1.0
