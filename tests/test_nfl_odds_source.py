from __future__ import annotations

import unittest

from sportsedge.odds_keyring import OddsKeyringError
from sportsedge.sports.nfl.odds_source import build_nfl_odds_url, fetch_nfl_odds


class NFLOddsSourceTests(unittest.TestCase):
    def test_sport_and_event_urls_have_fixed_market_contracts(self):
        sport = build_nfl_odds_url()
        event = build_nfl_odds_url(event_id="evt-1")
        self.assertIn("americanfootball_nfl/odds?", sport)
        self.assertIn("markets=h2h%2Cspreads%2Ctotals", sport)
        self.assertIn("events/evt-1/odds?", event)
        self.assertIn("alternate_spreads", event)
        self.assertIn("alternate_totals", event)
        with self.assertRaisesRegex(ValueError, "NFL_FORWARD_EVENT_ID_INVALID"):
            build_nfl_odds_url(event_id="bad/id")

    def test_injected_fetcher_preserves_untouched_payload_and_key_slot(self):
        payload = [{"id": "evt-1", "bookmakers": [{"key": "draftkings"}]}]
        calls = []

        def fake(url, key):
            calls.append((url, key))
            return payload

        result = fetch_nfl_odds(["key-one"], fetcher=fake)
        self.assertEqual(result.value, payload)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], "key-one")

    def test_terminal_account_exhaustion_does_not_try_backup_key(self):
        calls = []

        def exhausted(url, key):
            calls.append((url, key))
            raise RuntimeError("NFL_FORWARD_ODDS_FETCH_FAILED:HTTP_401:OUT_OF_USAGE_CREDITS")

        with self.assertRaisesRegex(OddsKeyringError, "ODDS_API_TERMINAL_FAILURE"):
            fetch_nfl_odds(["key-one", "key-two"], fetcher=exhausted)
        self.assertEqual([key for _, key in calls], ["key-one"])

    def test_nonterminal_failure_can_try_backup_key(self):
        calls = []

        def transient(url, key):
            calls.append((url, key))
            if key == "key-one":
                raise RuntimeError("NFL_FORWARD_ODDS_FETCH_FAILED:HTTP_503")
            return []

        result = fetch_nfl_odds(["key-one", "key-two"], fetcher=transient)
        self.assertEqual(result.key_slot, 2)
        self.assertEqual([key for _, key in calls], ["key-one", "key-two"])

    def test_response_shape_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "NFL_FORWARD_SPORT_ODDS_NOT_LIST"):
            fetch_nfl_odds(["k"], fetcher=lambda url, key: {"bad": True})
        with self.assertRaisesRegex(ValueError, "NFL_FORWARD_EVENT_ODDS_NOT_OBJECT"):
            fetch_nfl_odds(["k"], event_id="evt-1", fetcher=lambda url, key: [])


if __name__ == "__main__":
    unittest.main()
