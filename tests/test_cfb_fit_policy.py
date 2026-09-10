from __future__ import annotations

import unittest

from sportsedge.sports.cfb.fit_policy import (
    CFBFitPolicyError,
    DEFAULT_CFB_RIDGE_ALPHA_GRID,
    fit_cfb_joint_score_model_temporal,
)


_METRIC_KEYS = (
    "off_ppa_rush", "off_ppa_dropback", "def_ppa_rush_allowed", "def_ppa_dropback_allowed",
    "off_success_rate", "def_success_rate_allowed", "standard_down_ppa",
    "passing_down_success_rate", "eckel_rate", "points_per_eckel", "points_per_drive",
    "net_field_position", "explosive_rate",
)


def _metrics(base: float, game: int) -> dict[str, float]:
    return {
        key: base + (index + 1) * 0.013 + (game % 5) * 0.007
        for index, key in enumerate(_METRIC_KEYS)
    }


def _rows(seasons: tuple[int, ...]) -> list[dict]:
    rows: list[dict] = []
    for season_index, season in enumerate(seasons):
        for game in range(12):
            home_strength = 0.20 + season_index * 0.015 + game * 0.011
            away_strength = 0.14 + season_index * 0.010 + (11 - game) * 0.008
            rows.append({
                "game_id": f"{season}-{game}",
                "season": season,
                "home_metrics": _metrics(home_strength, game),
                "away_metrics": _metrics(away_strength, game + 2),
                "neutral_site": game % 4 == 0,
                "weather": {
                    "game_indoor": game % 3 == 0,
                    "wind_speed": 5.0 + (game % 6),
                    "temperature": 52.0 + game,
                },
                "home_score": 24 + season_index + (game % 7) + int(home_strength * 8),
                "away_score": 18 + (game % 6) + int(away_strength * 7),
            })
    return rows


class CFBTemporalFitPolicyTests(unittest.TestCase):
    def test_temporal_selection_is_deterministic_and_strictly_forward(self) -> None:
        rows = _rows((2021, 2022, 2023, 2024, 2025))
        first_model, first = fit_cfb_joint_score_model_temporal(rows)
        second_model, second = fit_cfb_joint_score_model_temporal(rows)

        self.assertEqual(first, second)
        self.assertEqual(first_model.artifact_sha256(), second_model.artifact_sha256())
        self.assertIn(first["selected_alpha"], DEFAULT_CFB_RIDGE_ALPHA_GRID)
        self.assertEqual(first_model.ridge_alpha, first["selected_alpha"])
        self.assertEqual(first["mode"], "TEMPORAL_EXPANDING_SEASON_SELECTION")
        self.assertFalse(first["promotion_evidence"])

        self.assertEqual([fold["validation_season"] for fold in first["folds"]], [2023, 2024, 2025])
        for fold in first["folds"]:
            self.assertTrue(fold["train_seasons"])
            self.assertTrue(all(season < fold["validation_season"] for season in fold["train_seasons"]))
            self.assertGreaterEqual(fold["train_row_count"], 20)
            self.assertGreater(fold["validation_row_count"], 0)

    def test_policy_reports_non_promotional_coefficient_stability(self) -> None:
        model, policy = fit_cfb_joint_score_model_temporal(_rows((2021, 2022, 2023, 2024)))
        diagnostics = policy["coefficient_stability"]
        self.assertEqual(len(diagnostics), len(model.feature_names))
        self.assertEqual([row["feature"] for row in diagnostics], list(model.feature_names))
        for row in diagnostics:
            self.assertGreaterEqual(row["home_sign_stability_rate"], 0.0)
            self.assertLessEqual(row["home_sign_stability_rate"], 1.0)
            self.assertGreaterEqual(row["away_sign_stability_rate"], 0.0)
            self.assertLessEqual(row["away_sign_stability_rate"], 1.0)
            self.assertEqual(len(row["home_fold_coefficients"]), len(policy["folds"]))
            self.assertEqual(len(row["away_fold_coefficients"]), len(policy["folds"]))
        self.assertFalse(policy["promotion_evidence"])

    def test_less_than_three_seasons_fails_closed(self) -> None:
        with self.assertRaisesRegex(CFBFitPolicyError, "CFB_TEMPORAL_FIT_SEASONS_INSUFFICIENT"):
            fit_cfb_joint_score_model_temporal(_rows((2024, 2025)))


if __name__ == "__main__":
    unittest.main()
