from datetime import datetime, timezone
import unittest

from sportsedge.espn_game_odds_source import _parse_event
from sportsedge.mlb_source import GameSnapshot


class ESPNGameOddsSourceTests(unittest.TestCase):
    def _game(self):
        return GameSnapshot(
            game_pk=777,
            game_date="2026-08-17T23:40:00Z",
            status="Preview",
            away_id=119,
            away_name="Los Angeles Dodgers",
            home_id=115,
            home_name="Colorado Rockies",
            away_probable_pitcher_id=None,
            away_probable_pitcher_name=None,
            home_probable_pitcher_id=None,
            home_probable_pitcher_name=None,
            retrieved_at="2026-08-17T15:00:00+00:00",
            venue_id=19,
            official_date="2026-08-17",
        )

    def test_parses_moneyline_runline_total_into_canonical_quotes(self):
        event = {
            "competitions": [{
                "odds": [{
                    "provider": {"displayName": "DraftKings"},
                    "moneyline": {
                        "home": {"close": {"odds": "+150"}},
                        "away": {"close": {"odds": "-175"}},
                    },
                    "pointSpread": {
                        "home": {"close": {"line": "+1.5", "odds": "-110"}},
                        "away": {"close": {"line": "-1.5", "odds": "-110"}},
                    },
                    "total": {
                        "over": {"close": {"line": "o11.5", "odds": "-105"}},
                        "under": {"close": {"line": "u11.5", "odds": "-115"}},
                    },
                }]
            }]
        }
        snap = _parse_event(
            event,
            game=self._game(),
            fetched_at=datetime(2026, 8, 17, 15, 0, tzinfo=timezone.utc),
            ttl_seconds=300,
        )
        self.assertEqual(len(snap.quotes), 6)
        self.assertFalse(snap.failures)
        markets = [q["market"] for q in snap.quotes]
        self.assertEqual(markets.count("MONEYLINE"), 2)
        self.assertEqual(markets.count("RUN_LINE"), 2)
        self.assertEqual(markets.count("TOTALS"), 2)
        for quote in snap.quotes:
            self.assertEqual(quote["sportsbook"], "DraftKings")
            self.assertEqual(quote["quote_provider"], "ESPN_SCOREBOARD")
            self.assertEqual(quote["provider_timestamp_semantics"], "FETCH_TIME")

    def test_missing_market_is_failure_not_fabricated_quote(self):
        event = {"competitions": [{"odds": [{"provider": {"displayName": "DraftKings"}}]}]}
        snap = _parse_event(
            event,
            game=self._game(),
            fetched_at=datetime(2026, 8, 17, 15, 0, tzinfo=timezone.utc),
            ttl_seconds=300,
        )
        self.assertEqual(snap.quotes, ())
        self.assertEqual(len(snap.failures), 3)


if __name__ == "__main__":
    unittest.main()
