import unittest

from sportsedge.hitter_joint_engine import price_hitter_market
from sportsedge.pitcher_joint_engine import price_pitcher_market, PitcherJointEngineError


class HitterJointCoherenceTests(unittest.TestCase):
    def _base(self, market, line=0.5, side="OVER"):
        return {
            "game_id": "g1", "market": market, "entity_id": "b1", "line": line, "side": side,
            "feature_source_hash": "a" * 64,
            "features": {
                "projected_pa": 4.2,
                "p_single": 0.15,
                "p_double": 0.05,
                "p_triple": 0.01,
                "p_hr": 0.04,
                "p_bb": 0.09,
                "p_run_per_pa": 0.13,
                "p_rbi_per_pa": 0.12,
                "p_sb_per_pa": 0.025,
            },
        }

    def test_one_plus_hit_equals_total_bases_over_half(self):
        hits = price_hitter_market(self._base("HITS")).get("model_p")
        tb = price_hitter_market(self._base("TOTAL_BASES")).get("model_p")
        self.assertAlmostEqual(hits, tb, places=12)

    def test_home_run_is_subset_of_hit(self):
        hr = price_hitter_market(self._base("HOME_RUNS")).get("model_p")
        hit = price_hitter_market(self._base("HITS")).get("model_p")
        self.assertLessEqual(hr, hit)

    def test_xbh_is_subset_of_hit(self):
        xbh = price_hitter_market(self._base("EXTRA_BASE_HITS")).get("model_p")
        hit = price_hitter_market(self._base("HITS")).get("model_p")
        self.assertLessEqual(xbh, hit)

    def test_quote_side_does_not_change_model_identity(self):
        over = price_hitter_market(self._base("HITS", side="OVER"))
        under = price_hitter_market(self._base("HITS", side="UNDER"))
        self.assertEqual(over["model_input_hash"], under["model_input_hash"])

    def test_integer_push_conserves_probability(self):
        over = price_hitter_market(self._base("HITS", line=1.0, side="OVER"))
        under = price_hitter_market(self._base("HITS", line=1.0, side="UNDER"))
        self.assertAlmostEqual(over["model_p"] + under["model_p"] + over["push_p"], 1.0)


class PitcherJointCoherenceTests(unittest.TestCase):
    POOL = [
        {"strikeouts": 5, "outs": 15, "earned_runs": 2, "hits_allowed": 5, "walks_allowed": 2},
        {"strikeouts": 7, "outs": 18, "earned_runs": 1, "hits_allowed": 4, "walks_allowed": 1},
        {"strikeouts": 8, "outs": 19, "earned_runs": 3, "hits_allowed": 6, "walks_allowed": 2},
        {"strikeouts": 6, "outs": 21, "earned_runs": 0, "hits_allowed": 3, "walks_allowed": 3},
        {"strikeouts": 9, "outs": 20, "earned_runs": 4, "hits_allowed": 7, "walks_allowed": 1},
    ]

    def _base(self, market, line, side="OVER"):
        return {
            "game_id": "g1", "market": market, "entity_id": "p1", "line": line, "side": side,
            "feature_source_hash": "b" * 64, "features": {"history_pool": self.POOL},
        }

    def test_outs_support_is_physically_bounded(self):
        over = price_pitcher_market(self._base("PITCHER_OUTS", 27.0))
        self.assertEqual(over["model_p"], 0.0)

    def test_combined_pitcher_prop_uses_same_rows(self):
        result = price_pitcher_market(self._base("PITCHER_HITS_WALKS_ER", 8.5))
        expected = sum((r["hits_allowed"] + r["walks_allowed"] + r["earned_runs"]) > 8.5 for r in self.POOL) / len(self.POOL)
        self.assertAlmostEqual(result["model_p"], expected)

    def test_invalid_historical_outs_fail_closed(self):
        bad = list(self.POOL)
        bad[0] = {**bad[0], "outs": 28}
        model = self._base("PITCHER_OUTS", 17.5)
        model["features"] = {"history_pool": bad}
        with self.assertRaises(PitcherJointEngineError):
            price_pitcher_market(model)

    def test_integer_push_conserves_probability(self):
        over = price_pitcher_market(self._base("PITCHER_ER", 2.0, "OVER"))
        under = price_pitcher_market(self._base("PITCHER_ER", 2.0, "UNDER"))
        self.assertAlmostEqual(over["model_p"] + under["model_p"] + over["push_p"], 1.0)


if __name__ == "__main__":
    unittest.main()
