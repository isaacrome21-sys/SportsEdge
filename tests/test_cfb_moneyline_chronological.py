import unittest

from scripts.research_cfb_moneyline_chronological import (
    BREAKEVEN,
    THRESHOLD,
    fit_residual,
    grade,
    paired_moneylines,
    study,
)


def rows(year, count=80):
    return [
        {
            "game_id": f"{year}-{i}",
            "season": year,
            "model_margin": float(i % 9 - 4),
            "actual_margin": float((i % 7) - 3),
            "home_won": (i % 2) == 0,
            "home_ml": -110.0 if (i % 2) == 0 else 100.0,
        }
        for i in range(count)
    ]


class CFBMoneylineChronologicalTest(unittest.TestCase):
    def test_fixed_threshold_price(self):
        self.assertEqual(THRESHOLD, 3.0)
        self.assertAlmostEqual(BREAKEVEN, 110 / 210)

    def test_fit_fails_without_multi_season_data(self):
        with self.assertRaisesRegex(ValueError, "INSUFFICIENT"):
            fit_residual(rows(2020, 500))

    def test_future_seasons_never_enter_fits(self):
        data = [x for year in range(2017, 2026) for x in rows(year)]
        report = study(data)
        self.assertGreaterEqual(len(report["folds"]), 3)
        for fold in report["folds"]:
            self.assertLess(fold["fit"]["max_train_season"], fold["season"])
        self.assertFalse(report["authority"]["bets"])
        self.assertFalse(report["authority"]["forward_validated"])

    def test_grade_excludes_near_threshold(self):
        fit = {"intercept": 0.0, "weight": 1.0}
        data = [
            {"model_margin": 4.0, "home_won": True},
            {"model_margin": 1.0, "home_won": False},  # below threshold
            {"model_margin": -5.0, "home_won": False},
        ]
        result = grade(data, fit)
        self.assertEqual(result["decisions"], 2)
        self.assertEqual(result["wins"] + result["losses"], 2)

    def test_paired_moneylines_require_same_named_provider_two_sides(self):
        p = {"1": {"season": 2023, "model_margin": 8, "actual_margin": 4, "home_won": True}}
        cache = {
            "lines_2023": {
                "1": {"provider": "Book A", "home_moneyline": "-150", "away_moneyline": "+135"},
                "2": {"provider": "Book A", "home_moneyline": -110},
            }
        }
        result = paired_moneylines(p, cache)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["home_ml"], -150)
        self.assertEqual(result[0]["away_ml"], 135)
        self.assertEqual(result[0]["provider"], "Book A")
        self.assertIsNone(result[0]["quote_timestamp"])
        self.assertFalse(result[0]["authenticated_draftkings"])

    def test_paired_moneylines_rejects_unpaired_providerless_invalid_prices(self):
        p = {"1": {"season": 2023, "model_margin": 8, "actual_margin": 4, "home_won": True}}
        good = {"provider": "Book A", "home_moneyline": -130, "away_moneyline": 120}
        bad = [
            {"moneyline": -130},
            {"home_moneyline": -130, "away_moneyline": 120},
            {"provider": "Book A", "home_moneyline": -130},
            {"provider": "Book A", "home_moneyline": -130, "away_moneyline": True},
            {"provider": "Book A", "home_moneyline": -130.0, "away_moneyline": 120},
            {"provider": "Book A", "home_moneyline": -130, "away_moneyline": "NaN"},
            {"provider": "Book A", "home_moneyline": -130, "away_moneyline": "99"},
            {"provider": "Book A", "home_moneyline": -130, "away_moneyline": "+120.0"},
            {"providers": [
                {"provider": "Book A", "home_moneyline": -130},
                {"provider": "Book B", "away_moneyline": 120},
            ]},
        ]
        self.assertEqual(len(paired_moneylines(p, {"lines_2023": {"1": good}})), 1)
        for entry in bad:
            with self.subTest(entry=entry):
                self.assertEqual(
                    paired_moneylines(p, {"lines_2023": {"1": entry}}), []
                )

    def test_grade_labels_flat_price_return_as_synthetic(self):
        fit = {"intercept": 0.0, "weight": 1.0}
        result = grade([{"model_margin": 4, "home_won": True}], fit)
        self.assertEqual(result["synthetic_flat_minus_110_winner_return"], round(100 / 110, 5))
        self.assertNotIn("roi_at_assumed_minus_110", result)

    def test_no_coverage_yields_blocked_status(self):
        # Empty paired set must not invent an edge.
        report = study([])
        self.assertEqual(report["status"], "BLOCKED_NO_MONEYLINE_COVERAGE")
        self.assertEqual(report["pooled"]["decisions"], 0)
        self.assertFalse(report["authority"]["bets"])

    def test_small_test_set_never_passes_screen(self):
        report = study(rows(2025, 10))
        self.assertEqual(report["status"], "BLOCKED_INSUFFICIENT_CHRONO_TRAINING")
        self.assertEqual(report["pooled"]["decisions"], 0)
        self.assertFalse(report["authority"]["forward_validated"])

    def test_trainable_folds_without_selections_are_not_missing_price_coverage(self):
        from unittest.mock import patch

        data = [x for year in range(2017, 2026) for x in rows(year)]
        empty_grade = {
            "wins": 0,
            "losses": 0,
            "decisions": 0,
            "synthetic_flat_minus_110_winner_return": None,
        }
        with patch("scripts.research_cfb_moneyline_chronological.grade", return_value=empty_grade):
            report = study(data)
        self.assertGreater(len(report["folds"]), 0)
        self.assertEqual(report["status"], "BLOCKED_NO_ELIGIBLE_DECISIONS")
        self.assertEqual(report["pooled"]["decisions"], 0)
        self.assertFalse(report["authority"]["bets"])


    def test_nonfinite_training_row_cannot_turn_fit_into_nan(self):
        # Three historical seasons, 300 rows: one NaN previously poisoned
        # the OLS coefficients and generated an all-AWAY synthetic card.
        train = [r for y in (2018, 2019, 2020) for r in rows(y, 100)]
        good = fit_residual(train)
        self.assertTrue(__import__("math").isfinite(good["weight"]))
        for field in ("model_margin", "actual_margin"):
            for bad in (float("nan"), float("inf"), -float("inf"), "bad"):
                damaged = [dict(x) for x in train]
                damaged[0][field] = bad
                with self.subTest(field=field, bad=str(bad)):
                    with self.assertRaisesRegex(ValueError, "TRAINING_NONFINITE_OR_NONNUMERIC"):
                        fit_residual(damaged)

    def test_nonfinite_fit_and_holdout_refused_before_any_side_selection(self):
        valid = [
            {"model_margin": 4.0, "home_won": True},
            {"model_margin": -5.0, "home_won": False},
        ]
        self.assertEqual(grade(valid, {"intercept": 0.0, "weight": 1.0})["decisions"], 2)
        for bad in (float("nan"), float("inf"), -float("inf")):
            with self.subTest(fit=str(bad)):
                with self.assertRaisesRegex(ValueError, "GRADE_INVALID_FIT"):
                    grade(valid, {"intercept": bad, "weight": 1.0})
            with self.subTest(holdout=str(bad)):
                with self.assertRaisesRegex(ValueError, "GRADE_INVALID_HOLDOUT"):
                    grade(valid + [{"model_margin": bad, "home_won": True}],
                          {"intercept": 0.0, "weight": 1.0})
        with self.assertRaisesRegex(ValueError, "GRADE_INVALID_HOLDOUT"):
            grade([{"model_margin": 4.0, "home_won": 1}],
                  {"intercept": 0.0, "weight": 1.0})


    def test_study_does_not_mislabel_corrupt_history_as_insufficient_training(self):
        # Each 2021-2025 fold uses 2017 as training; one nonfinite row must
        # invalidate the study rather than silently drop all five folds.
        data = [x for year in range(2017, 2026) for x in rows(year)]
        clean = study(data)
        self.assertEqual(len(clean["folds"]), 5)
        damaged = [dict(x) for x in data]
        damaged[0]["model_margin"] = float("nan")
        with self.assertRaisesRegex(ValueError, "TRAINING_NONFINITE_OR_NONNUMERIC"):
            study(damaged)

    def test_study_keeps_legitimate_insufficient_training_blocked(self):
        report = study(rows(2025, 10))
        self.assertEqual(report["status"], "BLOCKED_INSUFFICIENT_CHRONO_TRAINING")
        self.assertEqual(report["folds"], [])


if __name__ == "__main__":
    unittest.main()
