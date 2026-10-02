import unittest

from sportsedge.hitter_joint_engine import HITTER_MARKETS
from sportsedge.mlb_props_side_totals import SIDE_TOTAL_MARKETS, price_props_side_totals
from sportsedge.pitcher_joint_engine import PITCHER_MARKETS


class PropsSideTotalsProof(unittest.TestCase):
    def test_every_side_total_and_prop_prices(self):
        priced = price_props_side_totals()
        expected = set(SIDE_TOTAL_MARKETS) | set(HITTER_MARKETS) | set(PITCHER_MARKETS)
        self.assertEqual(set(priced), expected)
        for market, row in priced.items():
            self.assertGreaterEqual(row["model_p"], 0.0, market)
            self.assertLessEqual(row["model_p"], 1.0, market)
            self.assertEqual(row["authority"], "RESEARCH_READOUT_NOT_OFFICIAL")


if __name__ == "__main__":
    unittest.main()
