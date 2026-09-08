import unittest
from datetime import datetime, timedelta, timezone

from sportsedge.market_dislocation import MarketDislocationError, scan_market_dislocation

NOW = datetime(2026, 9, 8, 2, 0, tzinfo=timezone.utc)


def ml(book, side, team_id, odds, *, retrieved=NOW):
    return {
        "game_id": "777", "event_id": "777", "game_number": 1,
        "period": "FG", "market": "MONEYLINE", "entity_id": str(team_id),
        "team_id": str(team_id), "event_home_team_id": "20", "event_away_team_id": "10",
        "line": 0.0, "side": side, "american_odds": odds, "book_key": book,
        "retrieved_at": retrieved, "is_alternate": False,
    }


def total(book, side, line, odds, *, retrieved=NOW):
    return {
        "game_id": "777", "event_id": "777", "game_number": 1,
        "period": "FG", "market": "TOTALS", "entity_id": "777",
        "line": line, "side": side, "american_odds": odds, "book_key": book,
        "retrieved_at": retrieved, "is_alternate": False,
    }


class MarketDislocationTests(unittest.TestCase):
    def test_detects_stale_candidate_price_against_two_devigged_books(self):
        candidate = ml("draftkings", "HOME", 20, +110)
        snapshot = [
            ml("circa", "HOME", 20, -110), ml("circa", "AWAY", 10, -110),
            ml("pinnacle", "HOME", 20, -105), ml("pinnacle", "AWAY", 10, -105),
        ]
        result = scan_market_dislocation(candidate, snapshot, as_of=NOW, reference_books={"circa", "pinnacle"}, min_reference_books=2)
        self.assertEqual(result.status, "MARKET_DISLOCATION")
        self.assertAlmostEqual(result.reference_fair_probability, 0.5, places=12)
        self.assertGreater(result.probability_edge, 0.02)
        self.assertAlmostEqual(result.exact_market_ev_per_dollar, 0.05, places=12)
        self.assertFalse(result.push_mass_required_for_exact_ev)

    def test_raw_single_book_side_is_never_treated_as_fair(self):
        candidate = ml("draftkings", "HOME", 20, +110)
        snapshot = [ml("circa", "HOME", 20, -150), ml("pinnacle", "HOME", 20, -145)]
        result = scan_market_dislocation(candidate, snapshot, as_of=NOW, min_reference_books=2)
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.reason, "REFERENCE_BOOKS_INSUFFICIENT")
        self.assertIsNone(result.reference_fair_probability)

    def test_stale_reference_is_excluded(self):
        old = NOW - timedelta(minutes=10)
        candidate = ml("draftkings", "HOME", 20, +110)
        snapshot = [
            ml("circa", "HOME", 20, -110, retrieved=old), ml("circa", "AWAY", 10, -110, retrieved=old),
            ml("pinnacle", "HOME", 20, -110), ml("pinnacle", "AWAY", 10, -110),
        ]
        result = scan_market_dislocation(candidate, snapshot, as_of=NOW, max_age_seconds=120, min_reference_books=2)
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.reference_count, 1)

    def test_mismatched_threshold_is_not_reference(self):
        candidate = total("draftkings", "OVER", 8.5, +110)
        snapshot = [
            total("circa", "OVER", 9.5, -110), total("circa", "UNDER", 9.5, -110),
            total("pinnacle", "OVER", 8.5, -110), total("pinnacle", "UNDER", 8.5, -110),
        ]
        result = scan_market_dislocation(candidate, snapshot, as_of=NOW, min_reference_books=2)
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.reference_count, 1)

    def test_integer_total_does_not_fake_exact_ev_without_push_mass(self):
        candidate = total("draftkings", "OVER", 8.0, +110)
        snapshot = [
            total("circa", "OVER", 8.0, -110), total("circa", "UNDER", 8.0, -110),
            total("pinnacle", "OVER", 8.0, -110), total("pinnacle", "UNDER", 8.0, -110),
        ]
        result = scan_market_dislocation(candidate, snapshot, as_of=NOW, min_reference_books=2)
        self.assertEqual(result.status, "MARKET_DISLOCATION")
        self.assertTrue(result.push_mass_required_for_exact_ev)
        self.assertIsNone(result.exact_market_ev_per_dollar)
        self.assertGreater(result.conditional_ev_per_decision, 0)

    def test_model_probability_contamination_is_rejected(self):
        candidate = ml("draftkings", "HOME", 20, +110)
        candidate["model_p"] = 0.60
        with self.assertRaisesRegex(MarketDislocationError, "MODEL_DATA_PROHIBITED"):
            scan_market_dislocation(candidate, [], as_of=NOW, min_reference_books=1)


if __name__ == "__main__":
    unittest.main()
