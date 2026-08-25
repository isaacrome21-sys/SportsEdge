import unittest

from sportsedge.sports.nfl.m2 import price_nfl_m2_game_markets


class NFLM2SpreadSemanticsTests(unittest.TestCase):
    def test_home_minus_three_uses_margin_plus_home_handicap(self):
        distribution = [
            {"home_score": 24, "away_score": 21, "margin": 3, "total": 45},
            {"home_score": 23, "away_score": 21, "margin": 2, "total": 44},
            {"home_score": 25, "away_score": 21, "margin": 4, "total": 46},
        ]
        priced = price_nfl_m2_game_markets(
            distribution,
            spread_line=-3.0,
            total_line=45.0,
        )
        self.assertAlmostEqual(priced["spread"]["home"], 1.0 / 3.0)
        self.assertAlmostEqual(priced["spread"]["away"], 1.0 / 3.0)
        self.assertAlmostEqual(priced["spread"]["push"], 1.0 / 3.0)

    def test_pickem_spread_exactly_matches_moneyline_outcomes(self):
        distribution = [
            {"home_score": 24, "away_score": 21, "margin": 3, "total": 45},
            {"home_score": 20, "away_score": 23, "margin": -3, "total": 43},
            {"home_score": 17, "away_score": 17, "margin": 0, "total": 34},
        ]
        priced = price_nfl_m2_game_markets(
            distribution,
            spread_line=0.0,
            total_line=44.0,
        )
        self.assertEqual(priced["spread"]["home"], priced["moneyline"]["home"])
        self.assertEqual(priced["spread"]["away"], priced["moneyline"]["away"])
        self.assertEqual(priced["spread"]["push"], priced["moneyline"]["tie"])


if __name__ == "__main__":
    unittest.main()
