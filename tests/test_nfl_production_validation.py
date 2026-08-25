import copy
import unittest

from sportsedge.sports.nfl.m2 import NFL_M2_FEATURE_CONTRACT, PRODUCTION_NFL_M2_MODEL_ID, build_nfl_m2_features
from sportsedge.sports.nfl.production_validation import (
    build_production_nfl_raw_evaluations,
    build_production_nfl_validation_evidence,
    nflverse_spread_to_home_handicap,
)


class NFLProductionValidationTests(unittest.TestCase):
    def _feature(self, season, game, side):
        sign = 1.0 if side == "home" else -1.0
        strength = 0.015 * (season - 2017) + 0.01 * game * sign
        start = f"{season}-09-{10 + game:02d}T17:00:00+00:00"; asof = f"{season}-09-{9 + game:02d}T17:00:00+00:00"
        return build_nfl_m2_features({
            "off_epa": 0.05 + strength, "def_epa": -0.02 - 0.3 * strength,
            "pass_epa": 0.08 + strength, "rush_epa": 0.01 + 0.3 * strength,
            "opp_off_epa": 0.03 - 0.1 * strength, "opp_def_epa": -0.01 + 0.1 * strength,
            "pressure_for": 0.28 + 0.02 * sign, "pressure_allowed": 0.26 - 0.01 * sign,
            "success_rate": 0.44 + 0.05 * strength, "explosive_rate": 0.10 + 0.02 * strength,
            "rest_diff_days": sign, "travel_miles": 0.0 if side == "home" else 700.0,
            "timezone_crossings": 0.0 if side == "home" else 1.0, "short_week": 0.0, "bye_week": 0.0,
            "wind_mph": 8.0, "roof_closed": 0.0, "qb_id": f"{side}_{season}_{game}",
            "qb_adjustment": 0.8 * strength, "prior_efficiency": 0.4 * strength, "prior_weight": 0.5,
            "feature_asof_ts": asof, "game_start_ts": start,
        })

    def _rows(self):
        rows = []
        for season in range(2018, 2026):
            for game in range(1, 7):
                margin = 2.0 + 0.6 * game + 0.3 * (season - 2018) + ((game + season) % 3 - 1) * 4.0
                total = 42.0 + 0.4 * game + ((2 * game + season) % 4 - 1.5) * 3.0
                rows.append({
                    "game_id": f"{season}_{game}", "season": season, "week": game,
                    "home_features": self._feature(season, game, "home"), "away_features": self._feature(season, game, "away"),
                    "home_score": (total + margin) / 2.0, "away_score": (total - margin) / 2.0,
                    "spread_line": 3.5, "home_spread_odds": -110, "away_spread_odds": -110,
                    "total_line": 44.5, "over_odds": -110, "under_odds": -110,
                })
        return rows

    def test_nflverse_favorite_positive_line_converts_to_home_handicap(self):
        self.assertEqual(nflverse_spread_to_home_handicap(3.0), -3.0)
        self.assertEqual(nflverse_spread_to_home_handicap(-2.5), 2.5)
        self.assertEqual(nflverse_spread_to_home_handicap(0.0), 0.0)

    def test_raw_evaluations_are_fold_safe_and_use_joint_distribution(self):
        evaluations = build_production_nfl_raw_evaluations(self._rows(), min_train_seasons=2, ridge_alpha=1.0)
        self.assertTrue(evaluations)
        self.assertTrue(all(row["model_id"] == PRODUCTION_NFL_M2_MODEL_ID for row in evaluations))
        self.assertTrue(all(row["feature_contract"] == NFL_M2_FEATURE_CONTRACT for row in evaluations))
        self.assertTrue(all(row["season"] > max(row["train_seasons"]) for row in evaluations))
        self.assertTrue(all(row["home_handicap"] == -row["spread_line"] for row in evaluations))
        self.assertTrue(all(0.0 < row["m2_home_cover_prob"] < 1.0 for row in evaluations))
        self.assertTrue(all(0.0 < row["m2_over_prob"] < 1.0 for row in evaluations))

    def test_mutating_heldout_results_does_not_change_same_fold_model_probabilities(self):
        rows = self._rows(); baseline = build_production_nfl_raw_evaluations(rows, min_train_seasons=2, ridge_alpha=1.0)
        first_test = min(row["season"] for row in baseline); mutated = copy.deepcopy(rows)
        for row in mutated:
            if row["season"] == first_test:
                row["home_score"] += 50.0; row["away_score"] -= 25.0
        changed = build_production_nfl_raw_evaluations(mutated, min_train_seasons=2, ridge_alpha=1.0)
        left = [row for row in baseline if row["season"] == first_test]; right = [row for row in changed if row["season"] == first_test]
        self.assertEqual([(r["game_id"], r["m2_home_cover_prob"], r["m2_over_prob"]) for r in left],
                         [(r["game_id"], r["m2_home_cover_prob"], r["m2_over_prob"]) for r in right])

    def test_evidence_payload_is_exact_production_identity_and_reports_brier_and_log_loss(self):
        payload = build_production_nfl_validation_evidence(
            self._rows(), source_uri="frozen://nfl-m2-source-manifest", source_sha256="a" * 64,
            source_manifest_sha256="b" * 64, min_train_seasons=2, min_calibration_fit_seasons=2,
            calibration_min_bin_n=1, ridge_alpha=1.0,
        )
        self.assertEqual(payload["model_id"], PRODUCTION_NFL_M2_MODEL_ID)
        self.assertEqual(payload["feature_contract"], NFL_M2_FEATURE_CONTRACT)
        self.assertEqual(payload["source_manifest_sha256"], "b" * 64)
        self.assertEqual(payload["provenance"], "REAL_PUBLIC_HISTORY")
        self.assertTrue(payload["folds"]); self.assertIn("spread", payload["promotion_evidence"]); self.assertIn("total", payload["promotion_evidence"])
        for fold in payload["folds"]:
            self.assertIn("m1_log_loss", fold); self.assertIn("m2_log_loss", fold); self.assertIn("m1_brier", fold); self.assertIn("m2_brier", fold)

    def test_missing_market_prices_reduce_m1_coverage_not_m2_population(self):
        rows = self._rows(); rows[-1]["home_spread_odds"] = None; rows[-1]["away_spread_odds"] = None
        evaluations = build_production_nfl_raw_evaluations(rows, min_train_seasons=2, ridge_alpha=1.0)
        last = next(row for row in evaluations if row["game_id"] == rows[-1]["game_id"])
        self.assertIsNone(last["m1_home_cover_prob"]); self.assertIsNotNone(last["m2_home_cover_prob"])

    def test_missing_total_line_does_not_delete_spread_evidence(self):
        rows = self._rows(); rows[-1]["total_line"] = None
        evaluations = build_production_nfl_raw_evaluations(rows, min_train_seasons=2, ridge_alpha=1.0)
        last = next(row for row in evaluations if row["game_id"] == rows[-1]["game_id"])
        self.assertIsNotNone(last["m2_home_cover_prob"])
        self.assertIsNone(last["m2_over_prob"])
        self.assertIsNotNone(last["home_handicap"])

    def test_missing_spread_line_does_not_delete_total_evidence(self):
        rows = self._rows(); rows[-1]["spread_line"] = None
        evaluations = build_production_nfl_raw_evaluations(rows, min_train_seasons=2, ridge_alpha=1.0)
        last = next(row for row in evaluations if row["game_id"] == rows[-1]["game_id"])
        self.assertIsNone(last["m2_home_cover_prob"])
        self.assertIsNotNone(last["m2_over_prob"])
        self.assertIsNone(last["home_handicap"])


if __name__ == "__main__": unittest.main()
