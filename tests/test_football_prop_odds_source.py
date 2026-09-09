from __future__ import annotations

import unittest
from urllib.parse import parse_qs, urlparse

from sportsedge.football_prop_odds_source import (
    FootballPropOddsError,
    build_event_prop_odds_url,
    fetch_event_prop_odds,
)
from sportsedge.football_prop_run_machine import PROVIDER_MARKET_TO_STAT


class FootballPropOddsSourceTests(unittest.TestCase):
    def test_nfl_event_endpoint_requests_exact_supported_prop_surface(self):
        url = build_event_prop_odds_url(sport="NFL", event_id="evt-1")
        parsed = urlparse(url)
        self.assertIn("/sports/americanfootball_nfl/events/evt-1/odds", parsed.path)
        query = parse_qs(parsed.query)
        self.assertEqual(query["bookmakers"], ["draftkings"])
        self.assertEqual(set(query["markets"][0].split(",")), set(PROVIDER_MARKET_TO_STAT))
        self.assertNotIn("player_targets", query["markets"][0])

    def test_cfb_uses_ncaaf_event_endpoint(self):
        url = build_event_prop_odds_url(sport="CFB", event_id="abc")
        self.assertIn("americanfootball_ncaaf/events/abc/odds", url)

    def test_unknown_market_fails_closed(self):
        with self.assertRaisesRegex(FootballPropOddsError, "FOOTBALL_PROP_ODDS_MARKET_UNSUPPORTED"):
            build_event_prop_odds_url(sport="NFL", event_id="abc", markets=["player_targets"])

    def test_keyring_fetch_keeps_raw_event_payload(self):
        raw = {
            "id": "evt",
            "home_team": "H",
            "away_team": "A",
            "commence_time": "2026-09-09T20:00:00Z",
            "bookmakers": [],
        }
        seen = []
        def fetcher(url, key):
            seen.append((url, key))
            return raw
        result = fetch_event_prop_odds(["secret"], sport="NFL", event_id="evt", fetcher=fetcher)
        self.assertEqual(result.value, raw)
        self.assertEqual(seen[0][1], "secret")
        self.assertNotIn("secret", seen[0][0])


if __name__ == "__main__":
    unittest.main()
