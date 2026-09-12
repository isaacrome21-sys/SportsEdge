import copy
import unittest

from sportsedge.sports.nfl.m2 import build_nfl_m2_features
from sportsedge.sports.nfl.m2_v2_selector import (
    NFL_M2_V2_SELECTOR_CONTRACT,
    select_nfl_m2_v2_kernel_scales,
)
from sportsedge.sports.nfl.m2_v2_validation import (
    build_nfl_m2_v2_candidate_evidence,
    build_nfl_m2_v2_raw_evaluations,
)


class NFLM2V2NestedSelectorTests(unittest.TestCase):
    GRID = (0.75, 1.0, 1.25)

    def _features(self, *, season, index, side, strength):
        sign = 1.0 if side == "home" else -1.0
        start = f"{season}-09-{10 + index:02d}T17:00:00+00:00"
        asof = f"{season}-09-{9 + index:02d}T17:00:00+00:00"
        return build_nfl_m2_features({
            "off_epa": 0.08 + strength,
            "def_epa": -0.03 - 0.20 * strength,
            "pass_epa": 0.11 + 0.70 * strength,
            "rush_epa": 0.02 + 0.35 * strength,
            "opp_off_epa": 0.03 - 0.10 * strength,
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
            "feature_asof_ts": asof,
            "game_start_ts": start,
        })

    def _rows(self):
        score_pairs = (
            (24, 20), (27, 17), (20, 23), (31, 24), (17, 14), (28, 30),
        )
        rows = []
        for season in range(2019, 2025):
            for index in range(6):
                drift = 0.003 * (season - 2019)
                home_strength = 0.018 * (index + 1) + drift
                away_strength = -0.014 * (index + 1) + 0.5 * drift
                home_score, away_score = score_pairs[(season + index) % len(score_pairs)]
                rows.append({
                    "game_id": f"{season}_{index}",
                    "season": season,
                    "week": index + 1,
                    "home_features": self._features(
                        season=season, index=index, side="home", strength=home_strength,
                    ),
                    "away_features": self._features(
                        season=season, index=index, side="away", strength=away_strength,
                    ),
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

    def test_insufficient_inner_history_falls_back_to_legacy_scale(self):
        rows = [row for row in self._rows() if row["season"] <= 2020]
        result = select_nfl_m2_v2_kernel_scales(
            rows,
            ridge_alpha=2.0,
            scale_grid=self.GRID,
            min_inner_train_seasons=2,
            fallback_scale=1.25,
        )
        self.assertEqual(result["contract"], NFL_M2_V2_SELECTOR_CONTRACT)
        self.assertEqual(result["status"], "INSUFFICIENT_INNER_FOLDS_FALLBACK")
        self.assertFalse(result["market_data_used"])
        self.assertEqual(result["selected_margin_kernel_scale"], 1.25)
        self.assertEqual(result["selected_total_kernel_scale"], 1.25)
        self.assertEqual(result["candidate_scores"], [])

    def test_market_fields_cannot_change_nested_selection(self):
        rows = [row for row in self._rows() if row["season"] <= 2023]
        baseline = select_nfl_m2_v2_kernel_scales(
            rows,
            ridge_alpha=2.0,
            scale_grid=self.GRID,
            min_inner_train_seasons=2,
        )
        contaminated = copy.deepcopy(rows)
        for row in contaminated:
            row["spread_line"] = 99.5
            row["total_line"] = 999.5
            row["home_spread_odds"] = -10000
            row["away_spread_odds"] = 5000
            row["book"] = "MUST_NOT_ENTER_SELECTOR"
        changed = select_nfl_m2_v2_kernel_scales(
            contaminated,
            ridge_alpha=2.0,
            scale_grid=self.GRID,
            min_inner_train_seasons=2,
        )
        self.assertEqual(baseline, changed)
        self.assertEqual(baseline["status"], "SELECTED_FROM_INNER_WALK_FORWARD")
        self.assertFalse(baseline["market_data_used"])

    def test_outer_heldout_outcomes_cannot_change_same_fold_selection(self):
        rows = self._rows()
        baseline = build_nfl_m2_v2_raw_evaluations(
            rows,
            min_train_seasons=2,
            ridge_alpha=2.0,
            kernel_scale_grid=self.GRID,
            selector_min_inner_train_seasons=2,
        )
        first_test_season = min(row["season"] for row in baseline)
        mutated = copy.deepcopy(rows)
        for row in mutated:
            if row["season"] == first_test_season:
                row["home_score"] = 70
                row["away_score"] = 0
        changed = build_nfl_m2_v2_raw_evaluations(
            mutated,
            min_train_seasons=2,
            ridge_alpha=2.0,
            kernel_scale_grid=self.GRID,
            selector_min_inner_train_seasons=2,
        )
        keys = (
            "game_id",
            "margin_kernel_scale",
            "total_kernel_scale",
            "kernel_scale_selection_status",
            "m2_home_cover_prob",
            "m2_over_prob",
            "candidate_signed_key_probability",
        )
        left = [tuple(row[key] for key in keys) for row in baseline if row["season"] == first_test_season]
        right = [tuple(row[key] for key in keys) for row in changed if row["season"] == first_test_season]
        self.assertEqual(left, right)

    def test_evidence_exposes_nested_audit_but_remains_non_promotable(self):
        evidence = build_nfl_m2_v2_candidate_evidence(
            self._rows(),
            source_manifest_sha256="b" * 64,
            min_train_seasons=2,
            min_calibration_fit_seasons=2,
            calibration_min_bin_n=1,
            ridge_alpha=2.0,
            kernel_scale_grid=self.GRID,
            selector_min_inner_train_seasons=2,
        )
        self.assertEqual(evidence["status"], "DIAGNOSTIC_CANDIDATE_ONLY")
        self.assertFalse(evidence["promotion_eligible"])
        selector = evidence["nested_kernel_scale_selection"]
        self.assertTrue(selector["enabled"])
        self.assertEqual(selector["contract"], NFL_M2_V2_SELECTOR_CONTRACT)
        self.assertTrue(selector["outer_fold_audits"])
        for audit in selector["outer_fold_audits"]:
            self.assertFalse(audit["market_data_used"])
            self.assertNotIn(audit["outer_test_season"], audit["outer_training_seasons"])
            self.assertTrue(set(audit["inner_test_seasons"]).issubset(set(audit["outer_training_seasons"])))


if __name__ == "__main__":
    unittest.main()
