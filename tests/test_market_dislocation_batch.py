from datetime import datetime, timezone
import unittest

from sportsedge.market_dislocation_batch import (
    MarketDislocationBatchError,
    scan_dislocation_snapshot,
)

NOW = datetime(2026, 9, 8, 3, 0, tzinfo=timezone.utc)


def ml(book, side, team_id, odds):
    return {
        "game_id": "777", "event_id": "777", "game_number": 1,
        "period": "FG", "market": "MONEYLINE", "entity_id": str(team_id),
        "team_id": str(team_id), "event_home_team_id": "20", "event_away_team_id": "10",
        "line": 0.0, "side": side, "american_odds": odds, "book_key": book,
        "retrieved_at": NOW, "is_alternate": False,
    }


class MarketDislocationBatchTests(unittest.TestCase):
    def test_scans_target_book_against_reference_books(self):
        rows = [
            ml("draftkings", "HOME", 20, +110),
            ml("draftkings", "AWAY", 10, -120),
            ml("circa", "HOME", 20, -110), ml("circa", "AWAY", 10, -110),
            ml("pinnacle", "HOME", 20, -105), ml("pinnacle", "AWAY", 10, -105),
        ]
        batch = scan_dislocation_snapshot(
            rows,
            as_of=NOW,
            candidate_books={"draftkings"},
            reference_books={"circa", "pinnacle"},
        )
        self.assertEqual(len(batch.results), 2)
        self.assertFalse(batch.failures)
        home = next(x for x in batch.results if x.side == "HOME")
        self.assertEqual(home.status, "MARKET_DISLOCATION")

    def test_candidate_and_reference_books_must_be_independent(self):
        with self.assertRaisesRegex(MarketDislocationBatchError, "OVERLAP"):
            scan_dislocation_snapshot(
                [], as_of=NOW,
                candidate_books={"circa"}, reference_books={"circa"},
            )

    def test_invalid_candidate_is_reported_not_silently_dropped(self):
        bad = ml("draftkings", "HOME", 20, +110)
        bad.pop("event_id")
        batch = scan_dislocation_snapshot(
            [bad], as_of=NOW,
            candidate_books={"draftkings"}, reference_books={"circa"},
            min_reference_books=1,
        )
        self.assertFalse(batch.results)
        self.assertEqual(len(batch.failures), 1)
        self.assertIn("MISSING_REQUIRED_FIELD", batch.failures[0]["reason"])


if __name__ == "__main__":
    unittest.main()
