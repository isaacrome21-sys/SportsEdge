from datetime import datetime, timezone

from sportsedge.game_odds_source import parse_game_event_odds
from sportsedge.mlb_source import GameSnapshot


def _game():
    return GameSnapshot(
        game_pk=123,
        game_date="2026-08-11T23:40:00Z",
        status="Preview",
        away_id=10,
        away_name="Texas Rangers",
        home_id=20,
        home_name="Los Angeles Angels",
        away_probable_pitcher_id=101,
        away_probable_pitcher_name="Away SP",
        home_probable_pitcher_id=202,
        home_probable_pitcher_name="Home SP",
        retrieved_at="2026-08-11T23:30:00Z",
        official_date="2026-08-11",
    )


def _payload():
    return {
        "home_team": "Los Angeles Angels",
        "away_team": "Texas Rangers",
        "bookmakers": [{
            "key": "draftkings",
            "title": "DraftKings",
            "last_update": "2026-08-11T23:35:00Z",
            "markets": [
                {"key": "h2h", "last_update": "2026-08-11T23:35:00Z", "outcomes": [
                    {"name": "Texas Rangers", "price": 120},
                    {"name": "Los Angeles Angels", "price": -140},
                ]},
                {"key": "spreads", "last_update": "2026-08-11T23:35:00Z", "outcomes": [
                    {"name": "Texas Rangers", "point": 1.5, "price": -170},
                    {"name": "Los Angeles Angels", "point": -1.5, "price": 145},
                ]},
                {"key": "totals", "last_update": "2026-08-11T23:35:00Z", "outcomes": [
                    {"name": "Over", "point": 9.0, "price": -105},
                    {"name": "Under", "point": 9.0, "price": -115},
                ]},
            ],
        }],
    }


def test_parses_all_core_game_markets():
    snap = parse_game_event_odds(_payload(), game=_game())
    assert not snap.failures
    assert len(snap.quotes) == 6
    ml = [q for q in snap.quotes if q["market"] == "MONEYLINE"]
    rl = [q for q in snap.quotes if q["market"] == "RUN_LINE"]
    totals = [q for q in snap.quotes if q["market"] == "TOTALS"]
    assert {(q["side"], q["american_odds"]) for q in ml} == {("AWAY", 120), ("HOME", -140)}
    assert {(q["side"], float(q["line"])) for q in rl} == {("AWAY", 1.5), ("HOME", -1.5)}
    assert {(q["side"], float(q["line"])) for q in totals} == {("OVER", 9.0), ("UNDER", 9.0)}
    assert all(q["game_id"] == "123" for q in snap.quotes)
    assert all(q["ttl_seconds"] == 300 for q in snap.quotes)


def test_wrong_team_name_fails_closed_per_outcome():
    payload = _payload()
    payload["bookmakers"][0]["markets"][0]["outcomes"][0]["name"] = "Some Other Team"
    snap = parse_game_event_odds(payload, game=_game())
    assert any("ODDS_GAME_TEAM_UNRESOLVED" in x["reason"] for x in snap.failures)
    assert not any(q.get("selection") == "Some Other Team" for q in snap.quotes)
