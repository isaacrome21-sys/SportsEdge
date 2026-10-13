"""Regression tests: an API market is not a valid two-way quote just because it has two rows."""
import math
import unittest

from sportsedge.sports.nfl.fair_odds import american_to_decimal, price_event


HOME = "Jacksonville Jaguars"
AWAY = "Philadelphia Eagles"


def _book(book, market, sides):
    return {
        "key": book,
        "markets": [{"key": market, "outcomes": sides}],
    }


def _game(market, dk_sides, ref_sides=None):
    books = [_book("draftkings", market, dk_sides)]
    if ref_sides is not None:
        books.append(_book("pinnacle", market, ref_sides))
    return {"home_team": HOME, "away_team": AWAY, "bookmakers": books}


class FairOddsInputIntegrityTests(unittest.TestCase):
    def test_invalid_american_prices_fail_closed(self):
        for price in (0, 1, -1, 99, -99, math.inf, -math.inf, math.nan):
            with self.subTest(price=price):
                with self.assertRaises(ValueError):
                    american_to_decimal(price)
        self.assertEqual(american_to_decimal(-100), 2)
        self.assertEqual(american_to_decimal(100), 2)

    def test_malformed_totals_cannot_create_ev(self):
        bad_pairs = [
            [{"name": "Over", "point": 42.5, "price": -110},
             {"name": "Over", "point": 43.5, "price": -110}],
            [{"name": "Over", "point": 42.5, "price": -110},
             {"name": "Under", "point": 43.5, "price": -110}],
            [{"name": "Over", "point": float("nan"), "price": -110},
             {"name": "Under", "point": float("nan"), "price": -110}],
            [{"name": "Over", "point": 42.5, "price": -110.5},
             {"name": "Under", "point": 42.5, "price": -110}],
        ]
        for sides in bad_pairs:
            with self.subTest(sides=sides):
                self.assertEqual(price_event(_game("totals", sides)), [])

    def test_malformed_spreads_cannot_create_ev(self):
        bad_pairs = [
            [{"name": HOME, "point": -3.5, "price": -110},
             {"name": AWAY, "point": 3.0, "price": -110}],
            [{"name": HOME, "point": -3.5, "price": -110},
             {"name": HOME, "point": 3.5, "price": -110}],
        ]
        for sides in bad_pairs:
            with self.subTest(sides=sides):
                self.assertEqual(price_event(_game("spreads", sides)), [])

    def test_wrong_event_teams_are_rejected(self):
        sides = [{"name": "New York Jets", "price": -110},
                 {"name": "Buffalo Bills", "price": -110}]
        self.assertEqual(price_event(_game("h2h", sides)), [])

    def test_bad_reference_cannot_create_false_ev(self):
        dk = [{"name": "Over", "point": 42.5, "price": 110},
              {"name": "Under", "point": 42.5, "price": -130}]
        invalid_pinnacle = [{"name": "Over", "point": 42.5, "price": -150},
                            {"name": "Under", "point": 41.5, "price": 120}]
        rows = price_event(_game("totals", dk, invalid_pinnacle))
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["ev"] is None and row["fair_p"] is None for row in rows))

    def test_valid_opposing_market_still_prices(self):
        dk = [{"name": HOME, "point": -3.5, "price": -110},
              {"name": AWAY, "point": 3.5, "price": -110}]
        pinnacle = [{"name": HOME, "point": -3.5, "price": -115},
                    {"name": AWAY, "point": 3.5, "price": 105}]
        rows = price_event(_game("spreads", dk, pinnacle))
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["fair_p"] is not None for row in rows))


if __name__ == "__main__":
    unittest.main()
