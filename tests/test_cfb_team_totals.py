from __future__ import annotations

import unittest

from sportsedge.sports.cfb.joint_model import price_cfb_game_markets


class CFBTeamTotalPricingTests(unittest.TestCase):
    def test_prices_team_totals_from_joint_scores(self):
        distribution = (
            {"home_score": 31, "away_score": 17, "margin": 14, "total": 48},
            {"home_score": 24, "away_score": 24, "margin": 0, "total": 48},
            {"home_score": 17, "away_score": 27, "margin": -10, "total": 44},
            {"home_score": 28, "away_score": 21, "margin": 7, "total": 49},
        )
        priced = price_cfb_game_markets(
            distribution,
            spread_line=-3.5,
            total_line=47.5,
            home_team_total_line=24.5,
            away_team_total_line=23.5,
        )
        self.assertEqual(priced["home_team_total"]["over"], 0.5)
        self.assertEqual(priced["home_team_total"]["under"], 0.5)
        self.assertEqual(priced["home_team_total"]["push"], 0.0)
        self.assertEqual(priced["away_team_total"]["over"], 0.5)
        self.assertEqual(priced["away_team_total"]["under"], 0.5)
        self.assertEqual(priced["away_team_total"]["push"], 0.0)

    def test_empty_distribution_fails_closed(self):
        with self.assertRaisesRegex(Exception, "CFB_DISTRIBUTION_EMPTY"):
            price_cfb_game_markets([], spread_line=0.0, total_line=45.5)


if __name__ == "__main__":
    unittest.main()
