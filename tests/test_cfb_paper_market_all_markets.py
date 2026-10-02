from datetime import datetime, timezone

from scripts.run_cfb_paper_market import build_payload


NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)


def _event():
    return {
        "id": "g1",
        "away_team": "Away",
        "home_team": "Home",
        "commence_time": "2026-10-03T16:00:00Z",
        "bookmakers": [
            {
                "key": "draftkings",
                "markets": [
                    {"key": "h2h", "outcomes": [
                        {"name": "Away", "price": 150},
                        {"name": "Home", "price": -170},
                    ]},
                    {"key": "spreads", "outcomes": [
                        {"name": "Away", "point": 3.5, "price": 110},
                        {"name": "Home", "point": -3.5, "price": -130},
                    ]},
                    {"key": "totals", "outcomes": [
                        {"name": "Over", "point": 49.5, "price": 110},
                        {"name": "Under", "point": 49.5, "price": -130},
                    ]},
                ],
            },
            {
                "key": "fanduel",
                "markets": [
                    {"key": "h2h", "outcomes": [
                        {"name": "Away", "price": -110},
                        {"name": "Home", "price": -110},
                    ]},
                    {"key": "spreads", "outcomes": [
                        {"name": "Away", "point": 3.5, "price": -110},
                        {"name": "Home", "point": -3.5, "price": -110},
                    ]},
                    {"key": "totals", "outcomes": [
                        {"name": "Over", "point": 49.5, "price": -110},
                        {"name": "Under", "point": 49.5, "price": -110},
                    ]},
                ],
            },
            {
                "key": "betmgm",
                "markets": [
                    {"key": "h2h", "outcomes": [
                        {"name": "Away", "price": -105},
                        {"name": "Home", "price": -115},
                    ]},
                    {"key": "spreads", "outcomes": [
                        {"name": "Away", "point": 3.5, "price": -105},
                        {"name": "Home", "point": -3.5, "price": -115},
                    ]},
                    {"key": "totals", "outcomes": [
                        {"name": "Over", "point": 49.5, "price": -105},
                        {"name": "Under", "point": 49.5, "price": -115},
                    ]},
                ],
            },
        ],
    }


def test_moneyline_spread_total_are_all_scannable_research_only():
    payload = build_payload([_event()], 0.02, NOW, "TEST", "READY")
    markets = {row["market"] for row in payload["candidates"]}
    assert markets == {"MONEYLINE", "SPREAD", "TOTAL"}
    assert payload["markets"] == ["MONEYLINE", "SPREAD", "TOTAL"]
    assert all(row["model_p"] is None for row in payload["candidates"])
    assert all(row["official"] is False for row in payload["candidates"])
    assert not any(payload["authority"].values())


def test_spread_requires_exact_same_threshold_across_peer_books():
    event = _event()
    for book in event["bookmakers"][1:]:
        for market in book["markets"]:
            if market["key"] == "spreads":
                market["outcomes"][0]["point"] = 4.5
                market["outcomes"][1]["point"] = -4.5
    payload = build_payload([event], 0.02, NOW, "TEST", "READY")
    assert "SPREAD" not in {row["market"] for row in payload["candidates"]}


def test_total_requires_exact_same_threshold_across_peer_books():
    event = _event()
    for book in event["bookmakers"][1:]:
        for market in book["markets"]:
            if market["key"] == "totals":
                market["outcomes"][0]["point"] = 50.5
                market["outcomes"][1]["point"] = 50.5
    payload = build_payload([event], 0.02, NOW, "TEST", "READY")
    assert "TOTAL" not in {row["market"] for row in payload["candidates"]}
