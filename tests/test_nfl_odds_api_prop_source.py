from urllib.parse import parse_qs, urlparse

from sportsedge.sports.nfl.odds_api_prop_source import (
    MARKET_KEYS,
    build_nfl_prop_odds_url,
    normalize_nfl_prop_event,
)


def test_prop_url_requests_frozen_supported_market_set():
    url = build_nfl_prop_odds_url(event_id="evt123")
    qs = parse_qs(urlparse(url).query)
    assert qs["regions"] == ["us"]
    assert qs["bookmakers"] == ["draftkings,fanduel"]
    assert set(qs["markets"][0].split(",")) == set(MARKET_KEYS.values())
    assert "player_targets" not in qs["markets"][0]


def test_normalize_two_sided_receptions_and_anytime_td():
    payload = {
        "id": "evt123",
        "commence_time": "2026-09-13T18:00:00Z",
        "bookmakers": [
            {
                "key": "draftkings",
                "last_update": "2026-09-13T16:30:00Z",
                "markets": [
                    {
                        "key": "player_receptions",
                        "last_update": "2026-09-13T16:29:30Z",
                        "outcomes": [
                            {"name": "Over", "description": "Receiver One", "price": -115, "point": 5.5},
                            {"name": "Under", "description": "Receiver One", "price": -105, "point": 5.5},
                        ],
                    },
                    {
                        "key": "player_anytime_td",
                        "outcomes": [
                            {"name": "Yes", "description": "Runner One", "price": 135},
                            {"name": "No", "description": "Runner One", "price": -165},
                        ],
                    },
                ],
            }
        ],
    }
    rows = normalize_nfl_prop_event(payload)
    rec = [r for r in rows if r["market"] == "RECEPTIONS"]
    assert len(rec) == 2
    assert {r["side"] for r in rec} == {"OVER", "UNDER"}
    assert {r["line"] for r in rec} == {5.5}
    td = [r for r in rows if r["market"] == "ANYTIME_TD"]
    assert len(td) == 2
    assert {r["side"] for r in td} == {"YES", "NO"}
    assert {r["line"] for r in td} == {None}
    assert all(r["promotion_authority"] is False for r in rows)
