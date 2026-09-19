import unittest

from sportsedge.sports.cfb.full_game_derivatives import (
    AUTHORITY,
    price_cfb_full_game_derivatives,
)
from sportsedge.sports.cfb.joint_model import CFBModelError


PATHS = (
    {"home_score": 31, "away_score": 17, "margin": 14, "total": 48},
    {"home_score": 24, "away_score": 24, "margin": 0, "total": 48},
    {"home_score": 20, "away_score": 27, "margin": -7, "total": 47},
    {"home_score": 28, "away_score": 21, "margin": 7, "total": 49},
)


class TestCFBFullGameDerivatives(unittest.TestCase):
    def test_authority_is_zero(self):
        self.assertFalse(any(AUTHORITY.values()))

    def test_team_totals_and_alts_share_the_same_paths(self):
        priced = price_cfb_full_game_derivatives(
            PATHS,
            period="FG",
            spread_line=-3.5,
            total_line=48.0,
            home_team_total_line=24.5,
            away_team_total_line=23.5,
            alternate_spreads=(-7.0, 3.0),
            alternate_totals=(44.5, 51.5),
        )
        self.assertEqual(priced["period"], "FG")
        self.assertEqual(priced["bet_status"], "BLOCKED")
        self.assertEqual(priced["promotion_block_reason"], "CFB_PROMOTION_EVIDENCE_REQUIRED")
        self.assertAlmostEqual(priced["home_team_total"]["over"] + priced["home_team_total"]["under"] + priced["home_team_total"]["push"], 1.0)
        self.assertIn("-7.0", priced["alternate_spread"])
        self.assertIn("44.5", priced["alternate_total"])

    def test_rejects_non_fg_period(self):
        with self.assertRaises(CFBModelError):
            price_cfb_full_game_derivatives(PATHS, period="1H", spread_line=-3.0, total_line=50.0)

    def test_rejects_duplicate_alts(self):
        with self.assertRaises(CFBModelError):
            price_cfb_full_game_derivatives(
                PATHS, period="FG", spread_line=-3.0, total_line=50.0, alternate_spreads=(-3.0, -3.0)
            )


if __name__ == "__main__":
    unittest.main()
