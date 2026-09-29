import unittest

from sportsedge.hitter_joint_engine import price_hitter_market
from sportsedge.pitcher_joint_engine import price_pitcher_market


class MLBPredictiveCountKernelTests(unittest.TestCase):
    @staticmethod
    def pitcher_pool(outs):
        return [
            {
                "outs": value,
                "strikeouts": 5,
                "earned_runs": 2,
                "hits_allowed": 5,
                "walks_allowed": 2,
            }
            for value in outs
        ]

    @staticmethod
    def hitter_pool(n=10):
        return [
            {
                "plate_appearances": 4,
                "hits": 1,
                "singles": 1,
                "doubles": 0,
                "triples": 0,
                "home_runs": 0,
                "total_bases": 1,
                "rbi": 0,
                "runs": 0,
                "stolen_bases": 0,
                "walks": 0,
                "strikeouts": 1,
                "extra_base_hits": 0,
            }
            for _ in range(n)
        ]

    def pitcher(self, pool, side="OVER", line=13.5, market="PITCHER_OUTS", extra=None):
        features = {"history_pool": pool}
        if extra:
            features.update(extra)
        return price_pitcher_market({
            "game_id": "1",
            "entity_id": "2",
            "market": market,
            "side": side,
            "line": line,
            "features": features,
        })

    def test_ten_for_ten_is_not_a_hundred_percent_predictive_probability(self):
        pool = self.pitcher_pool([18] * 10)
        row = self.pitcher(pool)
        self.assertEqual(row["raw_empirical_p"], 1.0)
        self.assertGreater(row["model_p"], 0.5)
        self.assertLess(row["model_p"], 1.0)
        self.assertEqual(row["meta"]["predictive"]["support_upper"], 27.0)

    def test_boyd_example_keeps_raw_audit_but_smooths_tail(self):
        pool = self.pitcher_pool([21, 15, 16, 21, 16, 18, 18, 16, 21, 20])
        over = self.pitcher(pool, "OVER")
        under = self.pitcher(pool, "UNDER")
        self.assertEqual(over["raw_empirical_p"], 1.0)
        self.assertEqual(under["raw_empirical_p"], 0.0)
        self.assertGreater(over["model_p"], 0.9)
        self.assertLess(over["model_p"], 1.0)
        self.assertGreater(under["model_p"], 0.0)
        self.assertAlmostEqual(over["model_p"] + under["model_p"], 1.0, places=10)

    def test_integer_line_conserves_win_loss_push_mass(self):
        pool = self.pitcher_pool([15, 15, 16, 17, 18, 18, 19, 20, 20, 21])
        over = self.pitcher(pool, "OVER", line=18.0)
        under = self.pitcher(pool, "UNDER", line=18.0)
        self.assertAlmostEqual(over["push_p"], under["push_p"], places=12)
        self.assertAlmostEqual(over["model_p"] + under["model_p"] + over["push_p"], 1.0, places=10)

    def test_price_independent_target_mean_moves_distribution(self):
        pool = self.pitcher_pool([15, 16, 17, 18, 18, 19, 20, 20, 21, 21])
        for i, row in enumerate(pool):
            row["strikeouts"] = 4 + (i % 3)
        baseline = self.pitcher(pool, market="PITCHER_K", line=6.5)
        shifted = self.pitcher(
            pool,
            market="PITCHER_K",
            line=6.5,
            extra={"target_means": {"PITCHER_K": 8.0}},
        )
        self.assertGreater(shifted["model_p"], baseline["model_p"])

    def test_hitter_unseen_home_run_has_finite_predictive_tail(self):
        rows = self.hitter_pool()
        over = price_hitter_market({
            "game_id": "1",
            "entity_id": "3",
            "market": "HOME_RUNS",
            "side": "OVER",
            "line": 0.5,
            "features": {"history_pool": rows},
        })
        under = price_hitter_market({
            "game_id": "1",
            "entity_id": "3",
            "market": "HOME_RUNS",
            "side": "UNDER",
            "line": 0.5,
            "features": {"history_pool": rows},
        })
        self.assertEqual(over["raw_empirical_p"], 0.0)
        self.assertGreater(over["model_p"], 0.0)
        self.assertLess(over["model_p"], 0.5)
        self.assertAlmostEqual(over["model_p"] + under["model_p"], 1.0, places=10)

    def test_identical_input_is_deterministic(self):
        pool = self.pitcher_pool([14, 15, 16, 17, 18, 19, 20, 21, 18, 17])
        first = self.pitcher(pool)
        second = self.pitcher(pool)
        self.assertEqual(first["model_input_hash"], second["model_input_hash"])
        self.assertEqual(first["model_p"], second["model_p"])
        self.assertEqual(first["push_p"], second["push_p"])


if __name__ == "__main__":
    unittest.main()
