from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse
import unittest

from sportsedge.sports.nfl.team_total_quotes import (
    NFLTeamTotalQuoteError,
    build_nfl_team_total_url,
    parse_nfl_team_total_pairs,
)

NOW = datetime(2026, 10, 4, 16, 56, tzinfo=timezone.utc)


def _event(*, last_update="2026-10-04T16:55:00Z"):
    return {
        "id": "event-1",
        "sport_key": "americanfootball_nfl",
        "commence_time": "2026-10-04T17:00:00Z",
        "home_team": "Home Team",
        "away_team": "Away Team",
        "bookmakers": [{
            "key": "draftkings",
            "title": "DraftKings",
            "last_update": last_update,
            "markets": [{
                "key": "team_totals",
                "last_update": last_update,
                "outcomes": [
                    {"name": "Over", "description": "Home Team", "point": 24.5, "price": -110},
                    {"name": "Under", "description": "Home Team", "point": 24.5, "price": -110},
                    {"name": "Over", "description": "Away Team", "point": 21.5, "price": -105},
                    {"name": "Under", "description": "Away Team", "point": 21.5, "price": -115},
                ],
            }],
        }],
    }


class NFLTeamTotalQuoteTests(unittest.TestCase):
    def test_event_url_requests_only_draftkings_team_totals(self):
        url = build_nfl_team_total_url(event_id="event-1")
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        self.assertIn("/sports/americanfootball_nfl/events/event-1/odds", parsed.path)
        self.assertEqual(query["bookmakers"], ["draftkings"])
        self.assertEqual(query["markets"], ["team_totals"])

    def test_parser_requires_paired_same_line_prices_for_each_team(self):
        parsed = parse_nfl_team_total_pairs(
            _event(), now=NOW, expected_event_id="event-1"
        )
        self.assertEqual(parsed["home"]["line"], 24.5)
        self.assertEqual(parsed["away"]["line"], 21.5)
        self.assertEqual(parsed["book_key"], "draftkings")
        self.assertAlmostEqual(
            parsed["home"]["over_fair_market_p"] + parsed["home"]["under_fair_market_p"],
            1.0,
        )

    def test_wrong_event_identity_fails_closed(self):
        with self.assertRaisesRegex(NFLTeamTotalQuoteError, "EVENT_ID_MISMATCH"):
            parse_nfl_team_total_pairs(
                _event(), now=NOW, expected_event_id="different"
            )

    def test_stale_quote_fails_closed(self):
        with self.assertRaisesRegex(NFLTeamTotalQuoteError, "QUOTE_STALE"):
            parse_nfl_team_total_pairs(
                _event(last_update="2026-10-04T16:50:00Z"),
                now=NOW,
                expected_event_id="event-1",
            )

    def test_one_sided_team_total_fails_closed(self):
        event = _event()
        event["bookmakers"][0]["markets"][0]["outcomes"].pop(1)
        with self.assertRaisesRegex(NFLTeamTotalQuoteError, "PAIRED_PRICE_REQUIRED:home"):
            parse_nfl_team_total_pairs(event, now=NOW, expected_event_id="event-1")

    def test_mismatched_pair_line_fails_closed(self):
        event = _event()
        event["bookmakers"][0]["markets"][0]["outcomes"][1]["point"] = 25.5
        with self.assertRaisesRegex(NFLTeamTotalQuoteError, "LINE_PAIR_MISMATCH:home"):
            parse_nfl_team_total_pairs(event, now=NOW, expected_event_id="event-1")

    def test_team_identity_outside_event_fails_closed(self):
        event = _event()
        event["bookmakers"][0]["markets"][0]["outcomes"][0]["description"] = "Other Team"
        with self.assertRaisesRegex(NFLTeamTotalQuoteError, "TEAM_UNRESOLVED"):
            parse_nfl_team_total_pairs(event, now=NOW, expected_event_id="event-1")


if __name__ == "__main__":
    unittest.main()
