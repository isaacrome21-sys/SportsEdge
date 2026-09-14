from __future__ import annotations

from datetime import datetime, timezone
import json
import unittest

from sportsedge.market_data_contract import MarketDataContractError, PublicBettingSplit
from sportsedge.public_betting_context import divergence_label, normalize_split_row
from sportsedge.the_odds_api_live import (
    build_current_odds_url,
    build_historical_odds_url,
    normalize_response,
)

UTC = timezone.utc


class MarketDataProviderV1Tests(unittest.TestCase):
    def test_current_url_supports_books_and_markets(self):
        url = build_current_odds_url(
            api_key="secret",
            sport_key="americanfootball_nfl",
            markets=("h2h", "spreads", "totals"),
            bookmakers=("draftkings", "fanduel"),
        )
        self.assertIn("americanfootball_nfl", url)
        self.assertIn("bookmakers=draftkings%2Cfanduel", url)
        self.assertIn("markets=h2h%2Cspreads%2Ctotals", url)

    def test_historical_url_requires_timezone(self):
        with self.assertRaises(Exception):
            build_historical_odds_url(
                api_key="secret",
                sport_key="americanfootball_nfl",
                at=datetime(2026, 9, 13, 18, 0),
            )

    def test_normalizes_live_quote_and_preserves_raw_hash(self):
        payload = [{
            "id": "evt-1",
            "sport_key": "americanfootball_nfl",
            "commence_time": "2026-09-13T17:00:00Z",
            "home_team": "Home",
            "away_team": "Away",
            "bookmakers": [{
                "key": "draftkings",
                "last_update": "2026-09-13T18:00:00Z",
                "markets": [{
                    "key": "spreads",
                    "last_update": "2026-09-13T18:00:00Z",
                    "outcomes": [
                        {"name": "Home", "price": -110, "point": -3.5},
                        {"name": "Away", "price": -110, "point": 3.5},
                    ],
                }],
            }],
        }]
        quotes = normalize_response(
            payload,
            sport_key="americanfootball_nfl",
            captured_at=datetime(2026, 9, 13, 18, 1, tzinfo=UTC),
        )
        self.assertEqual(len(quotes), 2)
        self.assertTrue(all(q.in_play for q in quotes))
        self.assertEqual(quotes[0].book, "draftkings")
        self.assertEqual(len(quotes[0].raw_payload_sha256), 64)
        self.assertFalse(quotes[0].as_dict()["model_p_feature_authority"])
        self.assertTrue(quotes[0].as_dict()["market_binding_authority"])

    def test_public_split_is_context_only(self):
        split = normalize_split_row(
            {
                "event_key": "nyj-ten-2026-09-13",
                "market": "spread",
                "selection": "NYJ +1.5",
                "ticket_percent": "44%",
                "money_percent": "63%",
            },
            source="ACTION_NETWORK",
            sport_key="NFL",
            captured_at=datetime(2026, 9, 13, 16, 0, tzinfo=UTC),
        )
        self.assertEqual(split.money_ticket_divergence, 19.0)
        self.assertEqual(divergence_label(split), "STRONG_DIVERGENCE")
        payload = split.as_context_dict()
        self.assertTrue(payload["context_only"])
        self.assertFalse(payload["model_p_feature_authority"])
        self.assertFalse(payload["promotion_authority"])

    def test_public_split_rejects_invalid_percent(self):
        with self.assertRaises(Exception):
            normalize_split_row(
                {
                    "event_key": "x",
                    "market": "spread",
                    "selection": "A",
                    "ticket_percent": 101,
                },
                source="SCORESANDODDS",
                sport_key="NFL",
                captured_at=datetime(2026, 9, 13, 16, 0, tzinfo=UTC),
            )


if __name__ == "__main__":
    unittest.main()
