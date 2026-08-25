import unittest

from sportsedge.sports.nfl.historical_validation import (
    build_calibration_evidence,
    build_nfl_fold_rows,
    calibrate_nfl_evaluations,
)


class NFLHistoricalCalibrationTests(unittest.TestCase):
    def _evaluations(self):
        rows = []
        for season in range(2018, 2024):
            for i in range(30):
                outcome = int(i % 3 != 0)
                over = int(i % 2 == 0)
                rows.append({
                    "game_id": f"{season}_{i}",
                    "season": season,
                    "home_cover_outcome": outcome,
                    "over_outcome": over,
                    "m1_home_cover_prob": 0.50,
                    "m1_over_prob": 0.50,
                    "m2_home_cover_prob": 0.58 if outcome else 0.42,
                    "m2_over_prob": 0.57 if over else 0.43,
                })
        return rows

    def test_calibrator_uses_only_prior_seasons_and_marks_fit_seasons(self):
        calibrated = calibrate_nfl_evaluations(self._evaluations(), min_fit_seasons=2)
        first = next(row for row in calibrated if row["season"] == 2020)
        self.assertEqual(first["spread_calibration_fit_seasons"], (2018, 2019))
        self.assertEqual(first["total_calibration_fit_seasons"], (2018, 2019))
        self.assertNotIn(2020, first["spread_calibration_fit_seasons"])
        self.assertIsNotNone(first["m2_home_cover_calibrated_prob"])
        self.assertIsNotNone(first["m2_over_calibrated_prob"])

    def test_earliest_seasons_without_enough_training_history_remain_unattested(self):
        calibrated = calibrate_nfl_evaluations(self._evaluations(), min_fit_seasons=2)
        for season in (2018, 2019):
            row = next(item for item in calibrated if item["season"] == season)
            self.assertIsNone(row["m2_home_cover_calibrated_prob"])
            self.assertIsNone(row["m2_over_calibrated_prob"])

    def test_fold_log_loss_uses_held_out_calibrated_probabilities(self):
        calibrated = calibrate_nfl_evaluations(self._evaluations(), min_fit_seasons=2)
        folds = build_nfl_fold_rows(calibrated, require_calibrated=True)
        seasons = {row["season"] for row in folds}
        self.assertNotIn(2018, seasons)
        self.assertNotIn(2019, seasons)
        self.assertIn(2020, seasons)
        self.assertTrue(all(row["m2_probability_source"] == "FOLD_SAFE_ISOTONIC" for row in folds))

    def test_reliability_evidence_is_per_market_and_has_threshold(self):
        calibrated = calibrate_nfl_evaluations(self._evaluations(), min_fit_seasons=2)
        evidence = build_calibration_evidence(
            calibrated, bins=5, min_bin_n=10, max_bin_deviation_threshold=0.20
        )
        self.assertIn("spread", evidence)
        self.assertIn("total", evidence)
        for market in ("spread", "total"):
            row = evidence[market]
            self.assertGreater(row["n"], 0)
            self.assertGreater(row["eligible_bin_count"], 0)
            self.assertEqual(row["threshold"], 0.20)
            self.assertIsInstance(row["pass"], bool)
            self.assertGreaterEqual(row["max_bin_deviation"], 0.0)

    def test_calibration_evidence_fails_closed_when_bins_are_underpowered(self):
        calibrated = calibrate_nfl_evaluations(self._evaluations(), min_fit_seasons=2)
        evidence = build_calibration_evidence(
            calibrated, bins=10, min_bin_n=10000, max_bin_deviation_threshold=0.05
        )
        self.assertFalse(evidence["spread"]["pass"])
        self.assertIsNone(evidence["spread"]["max_bin_deviation"])
        self.assertEqual(evidence["spread"]["reason"], "CALIBRATION_BINS_UNDERPOWERED")


if __name__ == "__main__":
    unittest.main()
