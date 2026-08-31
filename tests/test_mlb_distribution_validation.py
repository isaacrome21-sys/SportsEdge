from __future__ import annotations

import unittest

from sportsedge.mlb_distribution_validation import (
    MLBDistributionValidationError,
    run_line_margin_calibration_report,
    total_runs_calibration_report,
)


class MLBDistributionValidationTests(unittest.TestCase):
    def test_total_run_mass_passes_when_simulated_matches_empirical(self):
        empirical = [{"total_runs": value} for value in ([7] * 15 + [8] * 15 + [9] * 10 + [10] * 60)]
        simulated = list(empirical)
        report = total_runs_calibration_report(empirical, simulated, tolerance=0.015)
        self.assertTrue(report.passed)
        report.require_pass()

    def test_total_run_mass_fails_when_key_cluster_missing(self):
        empirical = [{"total_runs": value} for value in ([7] * 20 + [8] * 10 + [9] * 10 + [10] * 60)]
        simulated = [{"total_runs": 10} for _ in range(100)]
        report = total_runs_calibration_report(empirical, simulated, tolerance=0.015)
        self.assertFalse(report.passed)
        with self.assertRaisesRegex(MLBDistributionValidationError, "CALIBRATION_FAILED"):
            report.require_pass()

    def test_run_line_one_run_mass_is_checked(self):
        empirical = [{"game_margin": value} for value in ([1] * 20 + [-1] * 20 + [2] * 60)]
        simulated = list(empirical)
        self.assertTrue(run_line_margin_calibration_report(empirical, simulated).passed)


if __name__ == "__main__":
    unittest.main()
