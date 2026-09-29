from __future__ import annotations

import unittest

from sportsedge.mlb_context_adjusted_validation import (
    actual_events,
    brier_score,
    continuous_metrics,
    expected_calibration_error,
    log_loss,
    summarize_predictions,
)


class MLBContextAdjustedValidationTests(unittest.TestCase):
    def test_binary_metrics_perfect_predictions(self):
        rows = [(1.0, 1), (0.0, 0), (1.0, 1), (0.0, 0)]
        self.assertAlmostEqual(brier_score(rows), 0.0)
        self.assertLess(log_loss(rows), 1e-9)
        self.assertAlmostEqual(expected_calibration_error(rows), 0.0)

    def test_continuous_metrics_keep_bias_sign(self):
        metrics = continuous_metrics([5.0, 5.0], [3.0, 4.0])
        self.assertAlmostEqual(metrics["mae"], 1.5)
        self.assertAlmostEqual(metrics["mean_error"], 1.5)
        self.assertGreater(metrics["rmse"], metrics["mae"])

    def test_actual_events_use_half_run_thresholds(self):
        events = actual_events(away_runs=3, home_runs=5)
        self.assertEqual(events["GAME_TOTAL_OVER_7.5"], 1)
        self.assertEqual(events["GAME_TOTAL_OVER_8.5"], 0)
        self.assertEqual(events["AWAY_TEAM_TOTAL_OVER_3.5"], 0)
        self.assertEqual(events["HOME_TEAM_TOTAL_OVER_4.5"], 1)

    def test_summary_uses_event_probabilities_and_run_means(self):
        outcomes = actual_events(away_runs=3, home_runs=5)
        probabilities = {name: 0.75 if outcome else 0.25 for name, outcome in outcomes.items()}
        games = [{
            "actual_away_runs": 3,
            "actual_home_runs": 5,
            "actual_events": outcomes,
            "predictions": {
                "candidate": {
                    "away_mean_runs": 3.25,
                    "home_mean_runs": 4.75,
                    "events": probabilities,
                }
            },
        }]
        summary = summarize_predictions(games, model_label="candidate")
        self.assertEqual(summary["games"], 1)
        self.assertEqual(summary["binary_event_observations"], len(outcomes))
        self.assertAlmostEqual(summary["binary"]["brier"], 0.0625)
        self.assertAlmostEqual(summary["runs"]["total"]["mean_error"], 0.0)


if __name__ == "__main__":
    unittest.main()
