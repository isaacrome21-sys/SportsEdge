import unittest

from sportsedge.sports.cfb.line_integrity import (
    AUTHORITY,
    CFBLineIntegrityError,
    audit_quote_snapshot,
    canonicalize_spread_pair,
    canonicalize_total_pair,
)


class TestCFBLineIntegrity(unittest.TestCase):
    def test_authority_is_zero(self):
        self.assertFalse(any(AUTHORITY.values()))

    def test_opposite_spreads_canonicalize_to_home(self):
        self.assertEqual(canonicalize_spread_pair(-7.5, 7.5), -7.5)

    def test_non_opposite_spreads_fail(self):
        with self.assertRaises(CFBLineIntegrityError):
            canonicalize_spread_pair(-7.5, 3.5)

    def test_totals_must_agree_and_be_plausible(self):
        self.assertEqual(canonicalize_total_pair(54.5, 54.5), 54.5)
        with self.assertRaises(CFBLineIntegrityError):
            canonicalize_total_pair(54.5, 51.5)
        with self.assertRaises(CFBLineIntegrityError):
            canonicalize_total_pair(9.5, 9.5)

    def test_audit_accepts_canonical_home_line_on_both_sides(self):
        quotes = [
            {"game_id": "g1", "book_key": "dk", "market": "SPREAD", "period": "FG",
             "side": "HOME", "line": -3.0, "retrieved_at": "t0"},
            {"game_id": "g1", "book_key": "dk", "market": "SPREAD", "period": "FG",
             "side": "AWAY", "line": -3.0, "retrieved_at": "t0"},
            {"game_id": "g1", "book_key": "dk", "market": "TOTAL", "period": "FG",
             "side": "OVER", "line": 58.5, "retrieved_at": "t0"},
            {"game_id": "g1", "book_key": "dk", "market": "TOTAL", "period": "FG",
             "side": "UNDER", "line": 58.5, "retrieved_at": "t0"},
            {"game_id": "g1", "book_key": "dk", "market": "MONEYLINE", "period": "FG",
             "side": "HOME", "line": 0.0, "retrieved_at": "t0"},
            {"game_id": "g1", "book_key": "dk", "market": "MONEYLINE", "period": "FG",
             "side": "AWAY", "line": 0.0, "retrieved_at": "t0"},
        ]
        counts = audit_quote_snapshot(quotes)
        self.assertEqual(counts["spread_pairs"], 1)
        self.assertEqual(counts["total_pairs"], 1)
        self.assertEqual(counts["moneylines"], 1)

    def test_non_fg_period_blocked(self):
        with self.assertRaises(CFBLineIntegrityError):
            audit_quote_snapshot([
                {"game_id": "g1", "book_key": "dk", "market": "TOTAL", "period": "1H",
                 "side": "OVER", "line": 27.5, "retrieved_at": "t0"},
            ])


if __name__ == "__main__":
    unittest.main()
