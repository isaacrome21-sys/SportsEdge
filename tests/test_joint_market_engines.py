import unittest

from sportsedge.hitter_joint_engine import price_hitter_market, HitterJointEngineError
from sportsedge.pitcher_joint_engine import price_pitcher_market, PitcherJointEngineError


class HitterJointCoherenceTests(unittest.TestCase):
    POOL = [
        {"plate_appearances": 4, "hits": 1, "home_runs": 0, "total_bases": 1, "rbi": 0, "runs": 1, "stolen_bases": 0, "walks": 1, "extra_base_hits": 0},
        {"plate_appearances": 4, "hits": 2, "home_runs": 1, "total_bases": 5, "rbi": 3, "runs": 2, "stolen_bases": 0, "walks": 0, "extra_base_hits": 1},
        {"plate_appearances": 5, "hits": 0, "home_runs": 0, "total_bases": 0, "rbi": 0, "runs": 0, "stolen_bases": 0, "walks": 1, "extra_base_hits": 0},
        {"plate_appearances": 4, "hits": 1, "home_runs": 0, "total_bases": 2, "rbi": 1, "runs": 0, "stolen_bases": 0, "walks": 0, "extra_base_hits": 1},
        {"plate_appearances": 4, "hits": 3, "home_runs": 0, "total_bases": 4, "rbi": 2, "runs": 1, "stolen_bases": 1, "walks": 0, "extra_base_hits": 1},
        {"plate_appearances": 4, "hits": 1, "home_runs": 1, "total_bases": 4, "rbi": 4, "runs": 1, "stolen_bases": 0, "walks": 0, "extra_base_hits": 1},
        {"plate_appearances": 5, "hits": 2, "home_runs": 0, "total_bases": 2, "rbi": 0, "runs": 1, "stolen_bases": 0, "walks": 1, "extra_base_hits": 0},
        {"plate_appearances": 4, "hits": 0, "home_runs": 0, "total_bases": 0, "rbi": 1, "runs": 0, "stolen_bases": 0, "walks": 1, "extra_base_hits": 0},
        {"plate_appearances": 4, "hits": 2, "home_runs": 0, "total_bases": 3, "rbi": 1, "runs": 2, "stolen_bases": 1, "walks": 0, "extra_base_hits": 1},
        {"plate_appearances": 4, "hits": 1, "home_runs": 0, "total_bases": 1, "rbi": 0, "runs": 0, "stolen_bases": 0, "walks": 2, "extra_base_hits": 0},
    ]

    def _base(self, market, line=0.5, side="OVER"):
        return {
            "game_id": "g1", "market": market, "entity_id": "b1", "line": line, "side": side,
            "feature_source_hash": "a" * 64, "features": {"history_pool": self.POOL},
        }

    def test_one_plus_hit_equals_total_bases_over_half(self):
        hits = price_hitter_market(self._base("HITS"))["model_p"]
        tb = price_hitter_market(self._base("TOTAL_BASES"))["model_p"]
        self.assertAlmostEqual(hits, tb, places=12)

    def test_home_run_and_xbh_are_subsets_of_hit(self):
        hr = price_hitter_market(self._base("HOME_RUNS"))["model_p"]
        xbh = price_hitter_market(self._base("EXTRA_BASE_HITS"))["model_p"]
        hit = price_hitter_market(self._base("HITS"))["model_p"]
        self.assertLessEqual(hr, xbh)
        self.assertLessEqual(xbh, hit)

    def test_combo_is_exact_arithmetic_on_same_rows(self):
        result = price_hitter_market(self._base("HITS_RUNS_RBIS", line=2.5))["model_p"]
        expected = sum((r["hits"] + r["runs"] + r["rbi"]) > 2.5 for r in self.POOL) / len(self.POOL)
        self.assertAlmostEqual(result, expected)

    def test_multi_rbi_game_is_supported(self):
        result = price_hitter_market(self._base("RBI", line=2.5))["model_p"]
        expected = sum(r["rbi"] > 2.5 for r in self.POOL) / len(self.POOL)
        self.assertAlmostEqual(result, expected)

    def test_quote_side_does_not_change_model_identity(self):
        over = price_hitter_market(self._base("HITS", side="OVER"))
        under = price_hitter_market(self._base("HITS", side="UNDER"))
        self.assertEqual(over["model_input_hash"], under["model_input_hash"])

    def test_integer_push_conserves_probability(self):
        over = price_hitter_market(self._base("HITS", line=1.0, side="OVER"))
        under = price_hitter_market(self._base("HITS", line=1.0, side="UNDER"))
        self.assertAlmostEqual(over["model_p"] + under["model_p"] + over["push_p"], 1.0)

    def test_incoherent_history_row_fails_closed(self):
        bad = list(self.POOL)
        bad[0] = {**bad[0], "home_runs": 2, "hits": 1}
        model = self._base("HITS")
        model["features"] = {"history_pool": bad}
        with self.assertRaises(HitterJointEngineError):
            price_hitter_market(model)


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
        self.assertEqual(price_pitcher_market(self._base("PITCHER_OUTS", 27.0))["model_p"], 0.0)

    def test_combined_pitcher_prop_uses_same_rows(self):
        result = price_pitcher_market(self._base("PITCHER_HITS_WALKS_ER", 8.5))["model_p"]
        expected = sum((r["hits_allowed"] + r["walks_allowed"] + r["earned_runs"]) > 8.5 for r in self.POOL) / len(self.POOL)
        self.assertAlmostEqual(result, expected)

    def test_invalid_historical_outs_fail_closed(self):
        bad = list(self.POOL); bad[0] = {**bad[0], "outs": 28}
        model = self._base("PITCHER_OUTS", 17.5); model["features"] = {"history_pool": bad}
        with self.assertRaises(PitcherJointEngineError):
            price_pitcher_market(model)

    def test_integer_push_conserves_probability(self):
        over = price_pitcher_market(self._base("PITCHER_ER", 2.0, "OVER"))
        under = price_pitcher_market(self._base("PITCHER_ER", 2.0, "UNDER"))
        self.assertAlmostEqual(over["model_p"] + under["model_p"] + over["push_p"], 1.0)


if __name__ == "__main__":
    unittest.main()
