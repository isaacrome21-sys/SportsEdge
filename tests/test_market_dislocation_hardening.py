from datetime import datetime, timezone
import unittest

from sportsedge.market_dislocation import MarketDislocationError, scan_market_dislocation

NOW = datetime(2026, 9, 8, 3, 0, tzinfo=timezone.utc)


def ml(book, side, team_id, odds, **extra):
    row = {
        "game_id": "777", "event_id": "777", "game_number": 1,
        "period": "FG", "market": "MONEYLINE", "entity_id": str(team_id),
        "team_id": str(team_id), "event_home_team_id": "20", "event_away_team_id": "10",
        "line": 0.0, "side": side, "american_odds": odds, "book_key": book,
        "retrieved_at": NOW, "is_alternate": False,
    }
    row.update(extra)
    return row


class MarketDislocationHardeningTests(unittest.TestCase):
    def test_conflicting_reference_books_block_instead_of_average(self):
        candidate = ml("draftkings", "HOME", 20, +120)
        # Circa no-vig HOME ~= 60%; Pinnacle no-vig HOME ~= 40%.
        refs = [
            ml("circa", "HOME", 20, -150), ml("circa", "AWAY", 10, +150),
            ml("pinnacle", "HOME", 20, +150), ml("pinnacle", "AWAY", 10, -150),
        ]
        result = scan_market_dislocation(
            candidate, refs, as_of=NOW, min_reference_books=2,
            max_reference_probability_spread=0.04,
        )
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.reason, "REFERENCE_MARKET_CONFLICT")
        self.assertIsNone(result.reference_fair_probability)
        self.assertGreater(result.reference_probability_spread, 0.04)

    def test_nested_model_data_is_rejected(self):
        candidate = ml("draftkings", "HOME", 20, +110, metadata={"model_p": 0.60})
        with self.assertRaisesRegex(MarketDislocationError, "MODEL_DATA_PROHIBITED"):
            scan_market_dislocation(candidate, [], as_of=NOW, min_reference_books=1)

    def test_unapproved_f5_semantics_block(self):
        candidate = ml("draftkings", "HOME", 20, +110)
        candidate.update(market="F5_MONEYLINE", period="F5")
        result = scan_market_dislocation(candidate, [], as_of=NOW, min_reference_books=1)
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.reason, "MARKET_SEMANTICS_NOT_APPROVED_FOR_DISLOCATION")


if __name__ == "__main__":
    unittest.main()
