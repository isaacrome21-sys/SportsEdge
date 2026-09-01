from datetime import datetime, timezone

from sportsedge.sports.cfb.auto_objective_sources import _rest_payload, _team_history


PIT = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)
CURRENT = {
    "game_id": "current",
    "kickoff_ts": "2026-09-12T18:00:00+00:00",
    "home_team": "HOME",
    "away_team": "AWAY",
    "neutral_site": False,
}


def row(game_id, kickoff, home, away, *, neutral=False, venue=None):
    return {
        "id": game_id,
        "startDate": kickoff,
        "homeTeam": home,
        "awayTeam": away,
        "neutralSite": neutral,
        "venue": venue,
        "venueId": game_id,
    }


def test_team_history_excludes_games_not_yet_played_at_pit():
    rows = [
        row("played", "2026-09-05T18:00:00Z", "X", "AWAY"),
        row("scheduled-before-current", "2026-09-10T18:00:00Z", "Y", "AWAY"),
    ]
    history = _team_history(
        rows=rows,
        team="AWAY",
        current_game_id="current",
        current_kickoff=datetime(2026, 9, 12, 18, 0, tzinfo=timezone.utc),
        as_of=PIT,
    )
    assert [item["game_id"] for item in history] == ["played"]


def test_rest_payload_is_strictly_prior_and_marks_unknown_travel_missing():
    rows = [
        row("g1", "2026-08-29T18:00:00Z", "A", "AWAY", venue="A Stadium"),
        row("g2", "2026-09-05T18:00:00Z", "B", "AWAY", venue="B Stadium"),
    ]
    payload = _rest_payload(team="AWAY", rows=rows, game=CURRENT, as_of=PIT)
    assert payload["previous_game_id"] == "g2"
    assert payload["days_rest_floor"] == 7
    assert payload["short_week"] is False
    assert payload["post_bye"] is False
    assert payload["consecutive_road_games_entering"] == 2
    assert payload["travel_distance_km"] is None
    assert payload["timezone_shift_hours"] is None
    assert payload["travel_status"] == "UNAVAILABLE_NO_COORDINATE_SOURCE"


def test_home_or_neutral_game_breaks_prior_road_streak():
    rows = [
        row("g1", "2026-08-22T18:00:00Z", "A", "AWAY"),
        row("g2", "2026-08-29T18:00:00Z", "AWAY", "B"),
        row("g3", "2026-09-05T18:00:00Z", "C", "AWAY"),
    ]
    payload = _rest_payload(team="AWAY", rows=rows, game=CURRENT, as_of=PIT)
    assert payload["consecutive_road_games_entering"] == 1


def test_no_prior_game_returns_missing_instead_of_zero_fill():
    assert _rest_payload(team="AWAY", rows=[], game=CURRENT, as_of=PIT) is None
