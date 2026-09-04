from __future__ import annotations

import unittest

from sportsedge.research.count_distribution_candidate import (
    CountDistributionCandidateError,
    fit_count_distribution,
    price_count_threshold,
)


class CountDistributionCandidateTests(unittest.TestCase):
    def test_overdispersed_history_uses_negative_binomial(self):
        values = [0, 0, 0, 1, 1, 1, 2, 2, 4, 6, 0, 5, 1, 3, 0, 7, 2, 0, 4, 1]
        fit = fit_count_distribution(values, shrinkage_games=5)
        self.assertEqual(fit.distribution, "NEGATIVE_BINOMIAL")
        self.assertIsNotNone(fit.dispersion_r)
        priced = price_count_threshold(fit, line=2.5)
        self.assertAlmostEqual(priced["over"] + priced["under"] + priced["push"], 1.0, places=10)
        self.assertEqual(priced["push"], 0.0)

    def test_integer_line_has_push_mass(self):
        fit = fit_count_distribution([1, 2, 2, 3, 1, 2, 4, 2, 1, 3, 2, 2], shrinkage_games=10)
        priced = price_count_threshold(fit, line=2)
        self.assertGreater(priced["push"], 0.0)
        self.assertAlmostEqual(priced["over"] + priced["under"] + priced["push"], 1.0, places=10)

    def test_underdispersed_history_falls_back_to_poisson(self):
        fit = fit_count_distribution([2] * 12, shrinkage_games=10)
        self.assertEqual(fit.distribution, "POISSON")
        self.assertIsNone(fit.dispersion_r)

    def test_requires_chronological_sample_size(self):
        with self.assertRaisesRegex(CountDistributionCandidateError, "INSUFFICIENT"):
            fit_count_distribution([1, 2, 3], min_history=10)


if __name__ == "__main__":
    unittest.main()
