import unittest

from sportsedge.research_diagnostics import (
    ablation_delta,
    population_stability_index,
    probability_metrics,
    regression_metrics,
)


class ResearchDiagnosticsTests(unittest.TestCase):
    def test_regression_metrics(self):
        m = regression_metrics([1.0, 3.0], [1.0, 1.0])
        self.assertAlmostEqual(m["rmse"], 2 ** 0.5)
        self.assertAlmostEqual(m["mae"], 1.0)
        self.assertAlmostEqual(m["mean_error"], 1.0)

    def test_probability_metrics_reward_better_probabilities(self):
        y = [0, 0, 1, 1]
        good = probability_metrics([0.1, 0.2, 0.8, 0.9], y, bins=4)
        bad = probability_metrics([0.4, 0.4, 0.6, 0.6], y, bins=4)
        self.assertLess(good["brier"], bad["brier"])
        self.assertLess(good["log_loss"], bad["log_loss"])

    def test_ablation_positive_delta_means_feature_helped(self):
        d = ablation_delta({"rmse": 10.0, "brier": 0.20}, {"rmse": 10.5, "brier": 0.22})
        self.assertAlmostEqual(d["delta_rmse"], 0.5)
        self.assertAlmostEqual(d["delta_brier"], 0.02)

    def test_psi_near_zero_for_identical_samples(self):
        x = [float(i) for i in range(100)]
        self.assertAlmostEqual(population_stability_index(x, x, bins=10), 0.0)

    def test_psi_detects_large_shift(self):
        ref = [float(i) for i in range(100)]
        cur = [float(i + 1000) for i in range(100)]
        self.assertGreater(population_stability_index(ref, cur, bins=10), 1.0)

    def test_probability_domain_is_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "PROBABILITY_DOMAIN"):
            probability_metrics([1.2], [1])


if __name__ == "__main__":
    unittest.main()
