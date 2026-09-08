import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sportsedge.market_dislocation import MarketDislocationError, scan_market_dislocation

NOW = datetime(2026, 9, 8, 14, 0, tzinfo=timezone.utc)
GAME = SimpleNamespace(game_pk=777, home_team_id=20, away_team_id=10, game_number=1)


def ml(book, side, team_id, odds, *, retrieved=NOW, home=20, away=10):
    return {
        "game_id": "777", "event_id": "777", "game_number": 1,
        "event_home_team_id": str(home), "event_away_team_id": str(away),
        "period": "FG", "market": "MONEYLINE", "entity_id": str(team_id),
        "line": 0.0, "side": side, "american_odds": odds,
        "book_key": book, "retrieved_at": retrieved, "is_alternate": False,
    }


def total(book, side, line, odds, *, retrieved=NOW):
    return {
        "game_id": "777", "event_id": "777", "game_number": 1,
        "event_home_team_id": "20", "event_away_team_id": "10",
        "period": "FG", "market": "TOTALS", "entity_id": "777",
        "line": line, "side": side, "american_odds": odds,
        "book_key": book, "retrieved_at": retrieved, "is_alternate": False,
    }


class MarketDislocationTests(unittest.TestCase):
    def test_detects_market_only_dislocation_from_two_devigged_books(self):
        candidate = ml("draftkings", "HOME", 20, +110)
        snapshot = [
            ml("circa", "HOME", 20, -110), ml("circa", "AWAY", 10, -110),
            ml("pinnacle", "HOME", 20, -105), ml("pinnacle", "AWAY", 10, -105),
        ]
        result = scan_market_dislocation(
            candidate, snapshot, game=GAME, as_of=NOW,
            reference_books={"circa", "pinnacle"}, min_reference_books=2,
        )
        self.assertEqual(result.status, "MARKET_DISLOCATION")
        self.assertAlmostEqual(result.reference_fair_probability, 0.5, places=12)
        self.assertGreater(result.probability_edge, 0.02)
        self.assertFalse(result.push_mass_required_for_exact_ev)

    def test_reference_with_wrong_official_team_identity_is_excluded(self):
        candidate = ml("draftkings", "HOME", 20, +110)
        snapshot = [
            ml("badbook", "HOME", 99, -110), ml("badbook", "AWAY", 10, -110),
            ml("circa", "HOME", 20, -110), ml("circa", "AWAY", 10, -110),
        ]
        result = scan_market_dislocation(candidate, snapshot, game=GAME, as_of=NOW, min_reference_books=2)
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.reference_count, 1)

    def test_stale_reference_is_excluded(self):
        old = NOW - timedelta(minutes=10)
        candidate = ml("draftkings", "HOME", 20, +110)
        snapshot = [
            ml("circa", "HOME", 20, -110, retrieved=old), ml("circa", "AWAY", 10, -110, retrieved=old),
            ml("pinnacle", "HOME", 20, -110), ml("pinnacle", "AWAY", 10, -110),
        ]
        result = scan_market_dislocation(candidate, snapshot, game=GAME, as_of=NOW, min_reference_books=2)
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.reference_count, 1)

    def test_integer_total_never_claims_exact_ev_without_push_mass(self):
        candidate = total("draftkings", "OVER", 8.0, +110)
        snapshot = [
            total("circa", "OVER", 8.0, -110), total("circa", "UNDER", 8.0, -110),
            total("pinnacle", "OVER", 8.0, -110), total("pinnacle", "UNDER", 8.0, -110),
        ]
        result = scan_market_dislocation(candidate, snapshot, game=GAME, as_of=NOW, min_reference_books=2)
        self.assertEqual(result.status, "MARKET_DISLOCATION")
        self.assertTrue(result.push_mass_required_for_exact_ev)
        self.assertIsNone(result.exact_market_ev_per_dollar)
        self.assertGreater(result.conditional_ev_per_decision, 0.0)

    def test_model_probability_contamination_is_rejected(self):
        candidate = ml("draftkings", "HOME", 20, +110)
        candidate["model_p"] = 0.60
        with self.assertRaisesRegex(MarketDislocationError, "MODEL_DATA_PROHIBITED"):
            scan_market_dislocation(candidate, [], game=GAME, as_of=NOW, min_reference_books=1)


if __name__ == "__main__":
    unittest.main()
