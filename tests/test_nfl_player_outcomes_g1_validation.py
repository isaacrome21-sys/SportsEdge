import unittest

from sportsedge.sports.nfl.player_outcomes_g1_validation import (
    chronological_receptions_readout,
    probability_metrics,
    quantity_metrics,
)


class NFLPlayerOutcomeG1ValidationTests(unittest.TestCase):
    def sample_rows(self):
        return [dict(player_id="p1", season=2025, week=i, receptions=v)
                for i, v in enumerate([2, 3, 4, 5, 6, 20], 1)]

    def test_duplicate_player_week_cannot_enter_history(self):
        rows = self.sample_rows()
        rows.append(dict(rows[-1], player_id=" p1 ", receptions=0))
        with self.assertRaisesRegex(ValueError, "DUPLICATE_PLAYER_WEEK"):
            chronological_receptions_readout(rows)

    def test_missing_or_invalid_outcomes_are_not_zero(self):
        for value in (None, "", -1, 1.5, float("nan"), float("inf"), True):
            for index in (0, 5):
                with self.subTest(value=value, index=index):
                    rows = self.sample_rows()
                    rows[index]["receptions"] = value
                    with self.assertRaisesRegex(ValueError, "INVALID_RECEPTIONS"):
                        chronological_receptions_readout(rows)

    def test_reversed_input_and_future_outcome_leave_earlier_prediction_unchanged(self):
        rows = self.sample_rows()
        expected = chronological_receptions_readout(rows)["predictions"][0]
        rows.append(dict(player_id="p1", season=2025, week=7, receptions=100))
        actual = chronological_receptions_readout(reversed(rows))["predictions"][0]
        self.assertEqual(expected, actual)

    def test_season_rollover_and_other_player_do_not_contaminate_history(self):
        rows = self.sample_rows()
        rows[-1].update(season=2026, week=1)
        rows.append(dict(player_id="p2", season=2025, week=1, receptions=100))
        prediction = chronological_receptions_readout(rows)["predictions"][0]
        self.assertEqual(prediction["predicted_mean"], 4)
        self.assertEqual(prediction["prior_game_count"], 5)

    def test_invalid_configuration_and_chronology(self):
        for value in (0, -1, True, 2.5):
            with self.assertRaisesRegex(ValueError, "INVALID_MIN_PRIOR_GAMES"):
                chronological_receptions_readout(self.sample_rows(), min_prior_games=value)
        for value in (-0.5, float("nan"), float("inf")):
            with self.assertRaisesRegex(ValueError, "INVALID_LINE"):
                chronological_receptions_readout(self.sample_rows(), line=value)
        for key in ("season", "week"):
            for value in (None, True, 0, 1.5, float("nan"), float("inf")):
                rows = self.sample_rows()
                rows[0][key] = value
                with self.assertRaisesRegex(ValueError, "INVALID_CHRONOLOGY"):
                    chronological_receptions_readout(rows)

    def test_invalid_metrics_are_rejected_before_clipping(self):
        for pair in ((2, .5), (.5, .5), (1, -0.1), (0, 1.1), (1, float("nan")), (0, float("inf"))):
            with self.assertRaisesRegex(ValueError, "INVALID_PROBABILITY_EVAL"):
                probability_metrics([pair])
        for pair in ((float("nan"), 1), (1, float("inf"))):
            with self.assertRaisesRegex(ValueError, "INVALID_QUANTITY_EVAL"):
                quantity_metrics([pair])

    def test_probability_metrics(self):
        result = probability_metrics([(1, 0.8), (0, 0.2)])
        self.assertEqual(result["n"], 2)
        self.assertLess(result["brier"], 0.05)
        self.assertLess(result["log_loss"], 0.3)

    def test_quantity_metrics(self):
        result = quantity_metrics([(5, 4), (3, 4)])
        self.assertEqual(result["n"], 2)
        self.assertAlmostEqual(result["mae"], 1.0)
        self.assertAlmostEqual(result["rmse"], 1.0)

    def test_walk_forward_never_uses_current_outcome(self):
        rows = []
        for week, receptions in enumerate([2, 3, 4, 5, 6, 20], start=1):
            rows.append({
                "player_id": "p1",
                "season": 2025,
                "week": week,
                "receptions": receptions,
            })
        out = chronological_receptions_readout(rows, line=4.5, min_prior_games=5)
        self.assertEqual(out["probability_metrics"]["n"], 1)
        pred = out["predictions"][0]
        self.assertEqual(pred["week"], 6)
        self.assertAlmostEqual(pred["predicted_mean"], 4.0)
        self.assertEqual(pred["actual_receptions"], 20.0)
        self.assertFalse(out["random_split_used"])
        self.assertFalse(out["market_prices_consumed"])


if __name__ == "__main__":
    unittest.main()
