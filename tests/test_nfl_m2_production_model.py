import copy
import unittest

from sportsedge.sports.nfl.m2 import (
    NFL_M2_FEATURE_CONTRACT,
    PRODUCTION_NFL_M2_MODEL_ID,
    build_nfl_m2_features,
    derive_nfl_m2_score_distribution,
    fit_nfl_m2_score_model,
    price_nfl_m2_game_markets,
    walkforward_fit_nfl_m2_score_model,
)


class NFLM2ProductionModelTests(unittest.TestCase):
    def _features(self, *, qb, strength, asof, start, side):
        sign = 1.0 if side == "home" else -1.0
        return build_nfl_m2_features({
            "off_epa": 0.08 + strength,
            "def_epa": -0.02 - 0.25 * strength,
            "pass_epa": 0.12 + strength,
            "rush_epa": 0.01 + 0.40 * strength,
            "opp_off_epa": 0.03 - 0.10 * strength,
            "opp_def_epa": -0.01 + 0.05 * strength,
            "pressure_for": 0.28 + 0.03 * sign + 0.05 * strength,
            "pressure_allowed": 0.25 - 0.02 * sign - 0.04 * strength,
            "success_rate": 0.44 + 0.08 * strength,
            "explosive_rate": 0.10 + 0.04 * strength,
            "rest_diff_days": sign,
            "travel_miles": 300.0 if side == "home" else 850.0,
            "timezone_crossings": 0.0 if side == "home" else 1.0,
            "short_week": 0.0,
            "bye_week": 0.0,
            "wind_mph": 8.0,
            "roof_closed": 0.0,
            "qb_id": qb,
            "qb_adjustment": 1.5 * strength,
            "prior_efficiency": 0.5 * strength,
            "prior_weight": 0.65,
            "feature_asof_ts": asof,
            "game_start_ts": start,
        })

    def _rows(self):
        rows = []
        for season in range(2018, 2024):
            for i in range(5):
                home_strength = 0.02 * (i + 1) + 0.002 * (season - 2018)
                away_strength = -0.015 * (i + 1) + 0.001 * (season - 2018)
                start = f"{season}-09-{10 + i:02d}T17:00:00+00:00"
                asof = f"{season}-09-{9 + i:02d}T17:00:00+00:00"
                home = self._features(
                    qb=f"H_{season}_{i}", strength=home_strength,
                    asof=asof, start=start, side="home",
                )
                away = self._features(
                    qb=f"A_{season}_{i}", strength=away_strength,
                    asof=asof, start=start, side="away",
                )
                margin = 3.0 + 80.0 * (home_strength - away_strength) + (i % 2) * 1.7
                total = 43.0 + 35.0 * (home_strength + away_strength) + ((season + i) % 3) * 1.3
                rows.append({
                    "game_id": f"{season}_{i}",
                    "season": season,
                    "week": i + 1,
                    "home_features": home,
                    "away_features": away,
                    "home_score": 0.5 * (total + margin),
                    "away_score": 0.5 * (total - margin),
                    # Market data may coexist at the evaluation row level, but
                    # must never be consumed by the M2 fit itself.
                    "spread_line": -3.5,
                    "total_line": 45.5,
                })
        return rows

    def test_feature_builder_marks_exact_market_blind_contract(self):
        row = self._rows()[0]
        self.assertEqual(row["home_features"]["feature_contract"], NFL_M2_FEATURE_CONTRACT)
        self.assertEqual(row["away_features"]["feature_contract"], NFL_M2_FEATURE_CONTRACT)

    def test_fit_requires_builder_contract_and_explicit_qb_identity(self):
        rows = self._rows()[:10]
        bad = copy.deepcopy(rows)
        bad[0]["home_features"].pop("feature_contract")
        with self.assertRaisesRegex(ValueError, "NFL_M2_FEATURE_CONTRACT_REQUIRED"):
            fit_nfl_m2_score_model(bad)

        bad = copy.deepcopy(rows)
        bad[0]["away_features"]["qb_id"] = ""
        with self.assertRaisesRegex(ValueError, "NFL_M2_QB_ID_REQUIRED"):
            fit_nfl_m2_score_model(bad)

    def test_fit_carries_joint_residual_structure_from_train_rows_only(self):
        model = fit_nfl_m2_score_model(self._rows()[:15], ridge_alpha=1.0)
        self.assertGreater(model.margin_sigma, 0.0)
        self.assertGreater(model.total_sigma, 0.0)
        self.assertGreaterEqual(model.residual_correlation, -1.0)
        self.assertLessEqual(model.residual_correlation, 1.0)
        self.assertEqual(len(model.residual_pairs), 15)

    def test_walkforward_is_season_ordered_and_emits_production_model_identity(self):
        predictions = walkforward_fit_nfl_m2_score_model(self._rows(), min_train_seasons=2, ridge_alpha=1.0)
        self.assertTrue(predictions)
        self.assertTrue(all(row["model_id"] == PRODUCTION_NFL_M2_MODEL_ID for row in predictions))
        self.assertTrue(all(row["feature_contract"] == NFL_M2_FEATURE_CONTRACT for row in predictions))
        self.assertTrue(all(row["season"] > max(row["train_seasons"]) for row in predictions))
        self.assertTrue(all(row["margin_sigma"] > 0.0 and row["total_sigma"] > 0.0 for row in predictions))

    def test_heldout_outcomes_cannot_change_the_same_fold_predictions(self):
        rows = self._rows()
        baseline = walkforward_fit_nfl_m2_score_model(rows, min_train_seasons=2, ridge_alpha=1.0)
        first_test_season = min(row["season"] for row in baseline)

        mutated = copy.deepcopy(rows)
        for row in mutated:
            if row["season"] == first_test_season:
                row["home_score"] += 70.0
                row["away_score"] -= 30.0
        changed = walkforward_fit_nfl_m2_score_model(mutated, min_train_seasons=2, ridge_alpha=1.0)

        left = [row for row in baseline if row["season"] == first_test_season]
        right = [row for row in changed if row["season"] == first_test_season]
        self.assertEqual(
            [(r["game_id"], r["model_margin_mu"], r["model_total_mu"], r["margin_sigma"], r["total_sigma"]) for r in left],
            [(r["game_id"], r["model_margin_mu"], r["model_total_mu"], r["margin_sigma"], r["total_sigma"]) for r in right],
        )

    def test_market_fields_at_game_row_level_do_not_change_fit(self):
        rows = self._rows()
        baseline = walkforward_fit_nfl_m2_score_model(rows, min_train_seasons=2, ridge_alpha=1.0)
        mutated = copy.deepcopy(rows)
        for row in mutated:
            row["spread_line"] = 99.5
            row["total_line"] = 999.0
            row["home_spread_odds"] = -10000
            row["book"] = "SHOULD_NOT_ENTER_M2"
        changed = walkforward_fit_nfl_m2_score_model(mutated, min_train_seasons=2, ridge_alpha=1.0)
        self.assertEqual(
            [(r["game_id"], r["model_margin_mu"], r["model_total_mu"]) for r in baseline],
            [(r["game_id"], r["model_margin_mu"], r["model_total_mu"]) for r in changed],
        )

    def test_joint_distribution_is_integer_reconciled_and_uses_train_residual_pairs(self):
        rows = self._rows()
        model = fit_nfl_m2_score_model(rows[:15], ridge_alpha=1.0)
        distribution = derive_nfl_m2_score_distribution(model, rows[15])
        self.assertEqual(len(distribution), len(model.residual_pairs))
        for path in distribution:
            self.assertIsInstance(path["home_score"], int)
            self.assertIsInstance(path["away_score"], int)
            self.assertGreaterEqual(path["home_score"], 0)
            self.assertGreaterEqual(path["away_score"], 0)
            self.assertEqual(path["margin"], path["home_score"] - path["away_score"])
            self.assertEqual(path["total"], path["home_score"] + path["away_score"])

    def test_market_lines_are_applied_only_after_joint_distribution_exists(self):
        rows = self._rows()
        model = fit_nfl_m2_score_model(rows[:15], ridge_alpha=1.0)
        distribution = derive_nfl_m2_score_distribution(model, rows[15])

        # Choose thresholds from the realized support of the already-built,
        # market-blind distribution.  The old hard-coded lines could both sit
        # on the same saturated side of every simulated outcome, producing
        # identical 1.0/0.0 readouts without implying any market leakage.
        margins = [float(row["margin"]) for row in distribution]
        totals = [float(row["total"]) for row in distribution]
        first = price_nfl_m2_game_markets(
            distribution,
            spread_line=-max(margins) - 0.5,
            total_line=min(totals) - 0.5,
        )
        second = price_nfl_m2_game_markets(
            distribution,
            spread_line=-min(margins) + 0.5,
            total_line=max(totals) + 0.5,
        )

        self.assertAlmostEqual(sum(first["spread"].values()), 1.0)
        self.assertAlmostEqual(sum(first["total"].values()), 1.0)
        self.assertNotEqual(first["spread"], second["spread"])
        self.assertNotEqual(first["total"], second["total"])
        self.assertAlmostEqual(first["moneyline"]["home"] + first["moneyline"]["away"] + first["moneyline"]["tie"], 1.0)
        self.assertEqual(first["moneyline"], second["moneyline"])

    def test_fit_is_deterministic(self):
        rows = self._rows()[:15]
        first = fit_nfl_m2_score_model(rows, ridge_alpha=2.0)
        second = fit_nfl_m2_score_model(rows, ridge_alpha=2.0)
        self.assertEqual(first.margin_coefficients, second.margin_coefficients)
        self.assertEqual(first.total_coefficients, second.total_coefficients)
        self.assertEqual(first.feature_means, second.feature_means)
        self.assertEqual(first.feature_scales, second.feature_scales)
        self.assertEqual(first.residual_pairs, second.residual_pairs)


if __name__ == "__main__":
    unittest.main()
