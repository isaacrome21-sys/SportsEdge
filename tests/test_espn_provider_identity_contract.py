from datetime import datetime, timezone
import unittest

from sportsedge.espn_game_odds_source import _parse_event
from sportsedge.mlb_source import GameSnapshot


class ESPNProviderIdentityContractTests(unittest.TestCase):
    def game(self):
        return GameSnapshot(
            game_pk=1, game_date="2026-09-15T23:00:00Z", status="Preview",
            away_id=1, away_name="Away", home_id=2, home_name="Home",
            away_probable_pitcher_id=None, away_probable_pitcher_name=None,
            home_probable_pitcher_id=None, home_probable_pitcher_name=None,
            retrieved_at="2026-09-15T14:59:30+00:00", venue_id=1,
            official_date="2026-09-15",
        )

    def test_transport_does_not_become_book_identity(self):
        event = {"competitions": [{"odds": [{
            "provider": {}, "lastUpdated": "2026-09-15T14:59:30Z",
            "moneyline": {"home": {"close": {"odds": "+100"}}, "away": {"close": {"odds": "-110"}}},
        }]}]}
        snap = _parse_event(event, game=self.game(), fetched_at=datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc), ttl_seconds=60)
        self.assertEqual(len(snap.quotes), 2)
        for quote in snap.quotes:
            self.assertEqual(quote["quote_provider"], "ESPN_SCOREBOARD")
            self.assertEqual(quote["sportsbook"], "ESPN partner")
            self.assertEqual(quote["book_key"], "espnpartner")
            self.assertNotEqual(quote["sportsbook"], "DraftKings")


if __name__ == "__main__":
    unittest.main()
