from datetime import datetime, timezone

from sportsedge.live_acquisition import LiveEventRef
from sportsedge.live_dispatcher import dispatch_event, dispatch_slate
from sportsedge.live_http_providers import TheOddsAPILiveProvider


NOW = datetime(2026, 8, 30, 1, 0, tzinfo=timezone.utc)


class StateOnlyProvider:
    name = "fixture-state"

    def fetch_state(self, event):
        return {"down": 1, "distance": 10}, NOW

    def fetch_quotes(self, event, markets):
        return ()


def event(status="LIVE", sport="NFL"):
    return LiveEventRef(
        sport=sport,
        event_id="evt-1",
        status=status,
        scheduled_start=NOW,
        home_team="Chicago Bears",
        away_team="Green Bay Packers",
    )


def test_run_it_includes_live_game_automatically():
    result = dispatch_event(event(), live_providers=(StateOnlyProvider(),))
    assert result.lane == "LIVE"
    assert result.status == "READY"
    assert result.live_bundle is not None


def test_run_it_routes_mixed_slate():
    results = dispatch_slate(
        (event("LIVE"), event("FINAL")),
        live_providers=(StateOnlyProvider(),),
    )
    assert results[0].lane == "LIVE"
    assert results[1].lane == "SETTLEMENT"
    assert results[1].status == "NO_NEW_BET"


def test_pregame_without_runner_reports_gap():
    result = dispatch_event(event("PREGAME"))
    assert result.lane == "PREGAME"
    assert result.status == "DATA_GAP"


def test_odds_provider_normalizes_two_way_main_markets():
    payload = [
        {
            "home_team": "Chicago Bears",
            "away_team": "Green Bay Packers",
            "bookmakers": [
                {
                    "key": "draftkings",
                    "last_update": "2026-08-30T01:00:00Z",
                    "markets": [
                        {
                            "key": "h2h",
                            "last_update": "2026-08-30T01:00:00Z",
                            "outcomes": [
                                {"name": "Chicago Bears", "price": -120},
                                {"name": "Green Bay Packers", "price": 100},
                            ],
                        },
                        {
                            "key": "totals",
                            "outcomes": [
                                {"name": "Over", "price": -110, "point": 44.5},
                                {"name": "Under", "price": -110, "point": 44.5},
                            ],
                        },
                    ],
                }
            ],
        }
    ]
    provider = TheOddsAPILiveProvider(api_key="fixture", get_json=lambda _: payload)
    quotes = tuple(provider.fetch_quotes(event(), ("MONEYLINE", "TOTAL")))
    assert {q.market for q in quotes} == {"MONEYLINE", "TOTAL"}
    assert all(q.paired for q in quotes)
    assert all(q.provider == "THE_ODDS_API" for q in quotes)


def test_three_way_market_is_not_silently_collapsed_to_two_way():
    payload = [
        {
            "home_team": "Chicago Bears",
            "away_team": "Green Bay Packers",
            "bookmakers": [
                {
                    "key": "fixture",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Chicago Bears", "price": 120},
                                {"name": "Draw", "price": 300},
                                {"name": "Green Bay Packers", "price": 120},
                            ],
                        }
                    ],
                }
            ],
        }
    ]
    provider = TheOddsAPILiveProvider(api_key="fixture", get_json=lambda _: payload)
    assert tuple(provider.fetch_quotes(event(), ("MONEYLINE",))) == ()
