from datetime import datetime, timezone

from sportsedge.sports.nfl.draftkings_prop_source import parse_nfl_category_payload


def test_parse_nfl_category_payload_normalizes_supported_markets_only():
    payload = {
        "markets": [
            {"id": "m1", "name": "Player Receptions"},
            {"id": "m2", "name": "Anytime Touchdown Scorer"},
            {"id": "m3", "name": "Unsupported Fancy Prop"},
        ],
        "selections": [
            {
                "marketId": "m1",
                "participantName": "Test Receiver",
                "label": "Over",
                "points": 5.5,
                "displayOdds": "-110",
            },
            {
                "marketId": "m1",
                "participantName": "Test Receiver",
                "label": "Under",
                "points": 5.5,
                "displayOdds": "+100",
            },
            {
                "marketId": "m2",
                "participantName": "Test Runner",
                "label": "Yes",
                "displayOdds": "+135",
            },
            {
                "marketId": "m3",
                "participantName": "Nobody",
                "label": "Over",
                "points": 1.5,
                "displayOdds": "-110",
            },
        ],
    }
    snap = parse_nfl_category_payload(
        payload,
        event_id=123,
        retrieved_at=datetime(2026, 9, 12, 13, 0, tzinfo=timezone.utc),
    )
    assert len(snap.quotes) == 3
    rec = [q for q in snap.quotes if q["market"] == "RECEPTIONS"]
    assert {q["side"] for q in rec} == {"OVER", "UNDER"}
    assert {q["line"] for q in rec} == {5.5}
    td = [q for q in snap.quotes if q["market"] == "ANYTIME_TD"]
    assert len(td) == 1
    assert td[0]["side"] == "YES"
    assert td[0]["line"] is None
    assert all(q["provider"] == "DRAFTKINGS_WEB_RESEARCH" for q in snap.quotes)


def test_parse_nfl_category_payload_skips_unknown_market_without_guessing():
    payload = {
        "markets": [{"id": "x", "name": "Longest Reception"}],
        "selections": [
            {
                "marketId": "x",
                "participantName": "Test Receiver",
                "label": "Over",
                "points": 24.5,
                "displayOdds": "-110",
            }
        ],
    }
    snap = parse_nfl_category_payload(payload, event_id=1)
    assert snap.quotes == ()
    assert snap.failures == ()


def test_parse_nfl_category_payload_rejects_missing_threshold_for_two_sided_prop():
    payload = {
        "markets": [{"id": "m", "name": "Passing Yards"}],
        "selections": [
            {
                "marketId": "m",
                "participantName": "Test QB",
                "label": "Over",
                "displayOdds": "-115",
            }
        ],
    }
    snap = parse_nfl_category_payload(payload, event_id=9)
    assert snap.quotes == ()
    assert len(snap.failures) == 1
    assert "DK_NFL_LINE_MISSING" in snap.failures[0]["reason"]
