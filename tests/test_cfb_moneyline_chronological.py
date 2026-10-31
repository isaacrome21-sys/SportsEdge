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
        self.assertIn(
            report["status"],
            ("NO_HISTORICALLY_VERIFIED_EDGE", "BLOCKED_NO_MONEYLINE_COVERAGE"),
        )


if __name__ == "__main__":
    unittest.main()
