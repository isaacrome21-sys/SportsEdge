import copy
import unittest

from sportsedge.sports.nfl.m2 import build_nfl_m2_features
from sportsedge.sports.nfl.m2_v2e_validation import (
    build_nfl_m2_v2e_candidate_evidence,
    build_nfl_m2_v2e_raw_evaluations,
)


class NFLM2V2EValidationTests(unittest.TestCase):
    def _features(self, season, index, side, strength):
        sign = 1.0 if side == "home" else -1.0
        return build_nfl_m2_features({
            "off_epa": 0.08 + strength,
            "def_epa": -0.03 - 0.2 * strength,
            "pass_epa": 0.11 + 0.7 * strength,
            "rush_epa": 0.02 + 0.35 * strength,
            "opp_off_epa": 0.03 - 0.1 * strength,
            "opp_def_epa": -0.01 + 0.05 * strength,
            "pressure_for": 0.27 + 0.02 * sign + 0.04 * strength,
            "pressure_allowed": 0.25 - 0.02 * sign - 0.03 * strength,
            "success_rate": 0.43 + 0.06 * strength,
            "explosive_rate": 0.10 + 0.03 * strength,
            "rest_diff_days": sign,
            "travel_miles": 250.0 if side == "home" else 800.0,
            "timezone_crossings": 0.0 if side == "home" else 1.0,
            "short_week": 0.0,
            "bye_week": 0.0,
            "wind_mph": 7.0 + index,
            "roof_closed": 0.0,
            "qb_id": f"{side}_{season}_{index}",
            "qb_adjustment": 1.2 * strength,
            "prior_efficiency": 0.5 * strength,
            "prior_weight": 0.65,
            "feature_asof_ts": f"{season}-09-{9 + index:02d}T17:00:00+00:00",
            "game_start_ts": f"{season}-09-{10 + index:02d}T17:00:00+00:00",
        })

    def _rows(self):
        scores = ((24, 20), (27, 17), (20, 23), (31, 24), (17, 14), (28, 30))
        rows = []
        for season in range(2019, 2025):
            for index in range(6):
                home_score, away_score = scores[(season + index) % len(scores)]
                rows.append({
                    "game_id": f"{season}_{index}",
                    "season": season,
                    "week": index + 1,
                    "home_features": self._features(season, index, "home", 0.02 * (index + 1)),
                    "away_features": self._features(season, index, "away", -0.015 * (index + 1)),
                    "home_score": home_score,
                    "away_score": away_score,
                    "spread_line": 3.5 if index % 2 == 0 else -2.5,
                    "total_line": 44.5 if index % 2 == 0 else 47.5,
                    "home_spread_odds": -110,
                    "away_spread_odds": -110,
                    "over_odds": -110,
                    "under_odds": -110,
                })
        return rows

    def test_outer_heldout_outcome_cannot_change_same_fold_probabilities(self):
        rows = self._rows()
        baseline = build_nfl_m2_v2e_raw_evaluations(rows, min_train_seasons=2, ridge_alpha=2.0)
        first_test = min(row["season"] for row in baseline)
        changed_rows = copy.deepcopy(rows)
        for row in changed_rows:
            if row["season"] == first_test:
                row["home_score"] = 70
                row["away_score"] = 0
        changed = build_nfl_m2_v2e_raw_evaluations(changed_rows, min_train_seasons=2, ridge_alpha=2.0)
        keys = ("game_id", "m2_home_cover_prob", "m2_over_prob", "candidate_signed_key_probability")
        left = [tuple(row[key] for key in keys) for row in baseline if row["season"] == first_test]
        right = [tuple(row[key] for key in keys) for row in changed if row["season"] == first_test]
        self.assertEqual(left, right)

    def test_market_prices_change_benchmark_not_model_distribution(self):
        rows = self._rows()
        baseline = build_nfl_m2_v2e_raw_evaluations(rows, min_train_seasons=2, ridge_alpha=2.0)
        changed_rows = copy.deepcopy(rows)
        for row in changed_rows:
            row["home_spread_odds"] = -400
            row["away_spread_odds"] = 300
            row["over_odds"] = 250
            row["under_odds"] = -350
            row["book"] = "MUST_NOT_ENTER_MODEL"
        changed = build_nfl_m2_v2e_raw_evaluations(changed_rows, min_train_seasons=2, ridge_alpha=2.0)
        for left, right in zip(baseline, changed):
            self.assertEqual(left["m2_home_cover_prob"], right["m2_home_cover_prob"])
            self.assertEqual(left["m2_over_prob"], right["m2_over_prob"])
            self.assertEqual(left["candidate_signed_key_probability"], right["candidate_signed_key_probability"])
        self.assertNotEqual(
            [row["m1_home_cover_prob"] for row in baseline],
            [row["m1_home_cover_prob"] for row in changed],
        )

    def test_evidence_is_diagnostic_and_crossfit_audited(self):
        evidence = build_nfl_m2_v2e_candidate_evidence(
            self._rows(),
            source_manifest_sha256="d" * 64,
            min_train_seasons=2,
            min_calibration_fit_seasons=2,
            calibration_min_bin_n=1,
            ridge_alpha=2.0,
        )
        self.assertEqual(evidence["status"], "DIAGNOSTIC_CANDIDATE_ONLY")
        self.assertFalse(evidence["promotion_eligible"])
        self.assertFalse(evidence["production_registry_consumes_this_artifact"])
        self.assertTrue(evidence["crossfit_support_audit"])
        for audit in evidence["crossfit_support_audit"]:
            self.assertNotIn(audit["outer_test_season"], audit["outer_train_seasons"])
            self.assertTrue(set(audit["dropped_support_seasons"]).issubset(set(audit["outer_train_seasons"])))


if __name__ == "__main__":
    unittest.main()
