import copy
import unittest

import numpy as np

from sportsedge.sports.nfl.location_symmetric_g1 import (
    DEFAULT_ALPHA_GRID,
    MARGIN_FEATURE_NAMES,
    MODEL_ID,
    TOTAL_FEATURE_NAMES,
    NFLSymmetricLocationError,
    discrete_v2_grid_from_location,
    fit_nfl_location_symmetric_g1,
    margin_feature_vector,
    select_training_only_alpha,
    team_means_from_location,
    total_feature_vector,
)
from sportsedge.sports.nfl.location_symmetric_g1_validation import (
    OUTER_TEST_SEASONS,
    validate_nfl_location_symmetric_g1,
)
from sportsedge.sports.nfl.m2 import build_nfl_m2_features


class NFLSymmetricLocationG1Tests(unittest.TestCase):
    def _features(
        self,
        *,
        qb: str,
        strength: float,
        asof: str,
        start: str,
        side: str,
        season_offset: float = 0.0,
    ):
        is_home = side == "home"
        sign = 1.0 if is_home else -1.0
        return build_nfl_m2_features({
            "off_epa": 0.04 + strength,
            "def_epa": -0.01 - 0.20 * strength,
            "pass_epa": 0.08 + 0.90 * strength,
            "rush_epa": 0.01 + 0.35 * strength,
            "opp_off_epa": 0.02 - 0.10 * strength,
            "opp_def_epa": -0.01 + 0.05 * strength,
            "pressure_for": 0.27 + 0.025 * sign + 0.04 * strength,
            "pressure_allowed": 0.26 - 0.02 * sign - 0.03 * strength,
            "success_rate": 0.43 + 0.06 * strength,
            "explosive_rate": 0.095 + 0.035 * strength,
            "rest_diff_days": 1.0 * sign + season_offset,
            "travel_miles": 0.0 if is_home else 450.0 + 80.0 * season_offset,
            "timezone_crossings": 0.0 if is_home else 1.0,
            "short_week": 1.0 if season_offset > 0.6 and not is_home else 0.0,
            "bye_week": 1.0 if season_offset < -0.6 and is_home else 0.0,
            "wind_mph": 7.0 + 2.0 * abs(season_offset),
            "roof_closed": 1.0 if season_offset > 0.8 else 0.0,
            "qb_id": qb,
            "qb_adjustment": 1.2 * strength,
            "prior_efficiency": 0.45 * strength,
            "prior_weight": 0.55 + 0.05 * min(4.0, abs(season_offset)),
            "feature_asof_ts": asof,
            "game_start_ts": start,
        })

    def _rows(self):
        rows = []
        for season in range(2018, 2026):
            for i in range(5):
                drift = 0.02 * (season - 2018)
                home_strength = 0.025 * (i + 1) + 0.006 * drift
                away_strength = -0.018 * (i + 1) + 0.004 * drift
                season_offset = ((season + i) % 5 - 2) / 2.0
                start = f"{season}-09-{10 + i:02d}T17:00:00+00:00"
                asof = f"{season}-09-{9 + i:02d}T17:00:00+00:00"
                home = self._features(
                    qb=f"H_{season}_{i}",
                    strength=home_strength,
                    asof=asof,
                    start=start,
                    side="home",
                    season_offset=season_offset,
                )
                away = self._features(
                    qb=f"A_{season}_{i}",
                    strength=away_strength,
                    asof=asof,
                    start=start,
                    side="away",
                    season_offset=-season_offset,
                )
                margin = (
                    2.4
                    + 72.0 * (home_strength - away_strength)
                    + 0.8 * ((i % 3) - 1)
                    + 0.25 * (season_offset)
                )
                total = (
                    43.0
                    + 32.0 * (home_strength + away_strength)
                    + 1.1 * ((season + i) % 4)
                    - 0.15 * (home["wind_mph"] + away["wind_mph"])
                )
                rows.append({
                    "game_id": f"{season}_{i}",
                    "season": season,
                    "week": i + 1,
                    "home_team": f"H{i}",
                    "away_team": f"A{i}",
                    "home_features": home,
                    "away_features": away,
                    "home_score": 0.5 * (total + margin),
                    "away_score": 0.5 * (total - margin),
                    "spread_line": -(margin * 0.70),
                    "total_line": total * 0.97,
                })
        return rows

    @staticmethod
    def _swap(row):
        out = copy.deepcopy(row)
        out["home_features"], out["away_features"] = (
            out["away_features"],
            out["home_features"],
        )
        out["home_team"], out["away_team"] = out.get("away_team"), out.get("home_team")
        return out

    def test_feature_dimensions_are_reduced_and_structurally_symmetric(self):
        row = self._rows()[0]
        swapped = self._swap(row)
        margin = margin_feature_vector(row)
        margin_swapped = margin_feature_vector(swapped)
        total = total_feature_vector(row)
        total_swapped = total_feature_vector(swapped)

        self.assertEqual(len(margin), len(MARGIN_FEATURE_NAMES))
        self.assertEqual(len(total), len(TOTAL_FEATURE_NAMES))
        np.testing.assert_allclose(margin_swapped, -margin, atol=0.0, rtol=0.0)
        np.testing.assert_allclose(total_swapped, total, atol=0.0, rtol=0.0)

    def test_fitted_prediction_obeys_raw_space_margin_symmetry_and_total_invariance(self):
        rows = [row for row in self._rows() if row["season"] <= 2022]
        model = fit_nfl_location_symmetric_g1(
            rows,
            margin_alpha=10.0,
            total_alpha=10.0,
        )
        row = self._rows()[-1]
        swapped = self._swap(row)
        margin, total = model.predict(row)
        swapped_margin, swapped_total = model.predict(swapped)

        self.assertEqual(model.model_id, MODEL_ID)
        self.assertAlmostEqual(
            margin + swapped_margin,
            2.0 * model.margin_intercept,
            places=10,
        )
        self.assertAlmostEqual(total, swapped_total, places=10)

    def test_nested_alpha_selection_is_deterministic_and_strictly_time_ordered(self):
        train = [row for row in self._rows() if row["season"] <= 2023]
        first = select_training_only_alpha(
            train,
            target="margin",
            alpha_grid=DEFAULT_ALPHA_GRID,
        )
        second = select_training_only_alpha(
            train,
            target="margin",
            alpha_grid=DEFAULT_ALPHA_GRID,
        )
        self.assertEqual(first, second)
        self.assertIn(first["selected_alpha"], DEFAULT_ALPHA_GRID)
        for candidate in first["candidates"]:
            for fold in candidate["folds"]:
                self.assertLess(max(fold["train_seasons"]), fold["test_season"])

    def test_root_market_fields_cannot_change_fit_or_prediction(self):
        rows = [row for row in self._rows() if row["season"] <= 2022]
        first = fit_nfl_location_symmetric_g1(
            rows,
            margin_alpha=10.0,
            total_alpha=100.0,
        )
        mutated = copy.deepcopy(rows)
        for row in mutated:
            row["spread_line"] = 99.5
            row["total_line"] = 999.5
            row["home_spread_odds"] = -10000
            row["sportsbook"] = "FORBIDDEN_IF_NESTED_BUT_ROOT_IS_EVALUATION_ONLY"
        second = fit_nfl_location_symmetric_g1(
            mutated,
            margin_alpha=10.0,
            total_alpha=100.0,
        )
        self.assertEqual(first.margin_coefficients, second.margin_coefficients)
        self.assertEqual(first.total_coefficients, second.total_coefficients)

    def test_nested_market_contamination_fails_closed(self):
        row = copy.deepcopy(self._rows()[0])
        row["home_features"]["spread_line"] = -3.5
        with self.assertRaisesRegex(ValueError, "M2_MARKET_DATA_PROHIBITED"):
            margin_feature_vector(row)

    def test_outer_test_outcome_cannot_change_that_folds_alpha_selection(self):
        rows = self._rows()
        baseline = validate_nfl_location_symmetric_g1(rows)
        mutated = copy.deepcopy(rows)
        for row in mutated:
            if row["season"] == 2021:
                row["home_score"] += 50.0
                row["away_score"] -= 20.0
        changed = validate_nfl_location_symmetric_g1(mutated)

        first_left = next(f for f in baseline["folds"] if f["test_season"] == 2021)
        first_right = next(f for f in changed["folds"] if f["test_season"] == 2021)
        self.assertEqual(
            first_left["alpha_selection"]["margin"]["selected_alpha"],
            first_right["alpha_selection"]["margin"]["selected_alpha"],
        )
        self.assertEqual(
            first_left["alpha_selection"]["total"]["selected_alpha"],
            first_right["alpha_selection"]["total"]["selected_alpha"],
        )

    def test_validation_uses_exact_preregistered_outer_folds_and_market_reference_sign(self):
        report = validate_nfl_location_symmetric_g1(self._rows())
        self.assertEqual(
            [fold["test_season"] for fold in report["folds"]],
            list(OUTER_TEST_SEASONS),
        )
        self.assertTrue(all(
            max(fold["train_seasons"]) < fold["test_season"]
            for fold in report["folds"]
        ))
        self.assertFalse(report["market_fields_used_as_model_inputs"])
        self.assertEqual(
            report["folds"][0]["margin"]["closing_market_reference"]["source_field"],
            "spread_line",
        )
        self.assertIn(report["status"], {
            "DEVELOPMENT_LOCATION_PASS",
            "DEVELOPMENT_LOCATION_FAIL",
        })

    def test_location_to_team_means_and_discrete_v2_handoff(self):
        means = team_means_from_location(4.0, 48.0)
        self.assertEqual(means, {"mean_home": 26.0, "mean_away": 22.0})
        grid = discrete_v2_grid_from_location(4.0, 48.0)
        self.assertAlmostEqual(sum(sum(row) for row in grid), 1.0, places=12)
        self.assertEqual(len(grid), 71)
        self.assertEqual(len(grid[0]), 71)

    def test_location_handoff_fails_closed_on_nonpositive_team_mean(self):
        with self.assertRaisesRegex(
            NFLSymmetricLocationError,
            "NFL_LOCATION_G1_TEAM_MEAN_NONPOSITIVE",
        ):
            team_means_from_location(50.0, 40.0)


if __name__ == "__main__":
    unittest.main()
