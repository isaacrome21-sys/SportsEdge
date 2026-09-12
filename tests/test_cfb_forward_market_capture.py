import json
from datetime import datetime, timezone
import unittest

from sportsedge.sports.cfb.forward_market_capture import (
    CFBForwardMarketError,
    plan_capture,
    validate_draftkings_snapshot,
)
from sportsedge.sports.cfb.odds_source import CFBOddsPayload, build_cfb_odds_url, fetch_cfb_odds


def _event(event_id: str, date: str, *, completed: bool = False):
    return {
        "id": event_id,
        "date": date,
        "status": {"type": {"completed": completed}},
    }


def _odds_payload():
    return [{
        "id": "provider-game-1",
        "commence_time": "2026-09-12T18:00:00Z",
        "bookmakers": [{
            "key": "draftkings",
            "markets": [
                {"key": "h2h", "outcomes": [{"name": "Home", "price": -120}, {"name": "Away", "price": 100}]},
                {"key": "spreads", "outcomes": [{"name": "Home", "price": -110, "point": -3.5}, {"name": "Away", "price": -110, "point": 3.5}]},
                {"key": "totals", "outcomes": [{"name": "Over", "price": -105, "point": 52.5}, {"name": "Under", "price": -115, "point": 52.5}]},
            ],
        }],
    }]


class CFBForwardMarketCaptureTests(unittest.TestCase):
    def test_decision_window_due_without_close(self):
        board = {"events": [_event("1", "2026-09-12T18:00:00Z")]}
        report = plan_capture([board], now="2026-09-12T16:30:00Z")
        self.assertTrue(report["capture_due"])
        self.assertEqual([x["scoreboard_event_id"] for x in report["decision_due"]], ["1"])
        self.assertEqual(report["close_due"], [])
        self.assertFalse(report["promotion_authority"])

    def test_close_window_due(self):
        board = {"events": [_event("1", "2026-09-12T18:00:00Z")]}
        report = plan_capture([board], now="2026-09-12T17:45:00Z")
        self.assertTrue(report["capture_due"])
        self.assertEqual([x["scoreboard_event_id"] for x in report["close_due"]], ["1"])

    def test_completed_and_past_games_do_not_trigger_paid_capture(self):
        board = {"events": [
            _event("done", "2026-09-12T18:00:00Z", completed=True),
            _event("past", "2026-09-12T16:00:00Z"),
        ]}
        report = plan_capture([board], now="2026-09-12T17:00:00Z")
        self.assertFalse(report["capture_due"])

    def test_snapshot_requires_two_sided_supported_market(self):
        payload = _odds_payload()
        report = validate_draftkings_snapshot(payload)
        self.assertTrue(report["snapshot_usable"])
        self.assertEqual(report["two_sided_market_count"], 3)
        payload[0]["bookmakers"][0]["markets"][0]["outcomes"] = [{"name": "Home", "price": -120}]
        with self.assertRaisesRegex(CFBForwardMarketError, "TWO_SIDED_OUTCOMES_REQUIRED"):
            validate_draftkings_snapshot(payload)

    def test_odds_url_is_cfb_draftkings_featured_markets_only(self):
        url = build_cfb_odds_url()
        self.assertIn("americanfootball_ncaaf", url)
        self.assertIn("bookmakers=draftkings", url)
        self.assertIn("markets=h2h%2Cspreads%2Ctotals", url)
        self.assertNotIn("alternate_spreads", url)

    def test_key_failover_returns_slot_without_exposing_key(self):
        calls = []
        raw = json.dumps(_odds_payload(), separators=(",", ":")).encode()

        def fake(url, key):
            calls.append((url, key))
            if key == "bad":
                raise RuntimeError("HTTP_401")
            return CFBOddsPayload(raw=raw, payload=_odds_payload())

        result = fetch_cfb_odds(["bad", "good"], fetcher=fake)
        self.assertEqual(result.key_slot, 2)
        self.assertEqual(len(result.failures), 1)
        self.assertEqual([key for _, key in calls], ["bad", "good"])
        self.assertNotIn("good", str(result.failures))


if __name__ == "__main__":
    unittest.main()
