import copy
import unittest

from sportsedge.sports.nfl.m2 import build_nfl_m2_features
from sportsedge.sports.nfl.m2_v2c_candidate import (
    NFL_M2_V2C_CANDIDATE_MODEL_ID,
    derive_nfl_m2_v2c_score_distribution,
    fit_nfl_m2_v2c_candidate,
)
from sportsedge.sports.nfl.m2_v2c_selector import select_nfl_m2_v2c_alphas
from sportsedge.sports.nfl.m2_v2c_validation import build_nfl_m2_v2c_raw_evaluations


class NFLM2V2CTests(unittest.TestCase):
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
        for season in range(2018, 2025):
            for i in range(6):
                start = f"{season}-09-{10 + i:02d}T17:00:00+00:00"
                asof = f"{season}-09-{9 + i:02d}T17:00:00+00:00"
                base = season - 2018
                home_score = 20 + ((i + base) % 12)
                away_score = 16 + ((2 * i + base) % 11)
                rows.append({
                    "game_id": f"{season}_{i}", "season": season, "week": i + 1,
                    "home_features": self._features(qb=f"H{season}{i}", strength=0.01 * (i + base), asof=asof, start=start, side="home"),
                    "away_features": self._features(qb=f"A{season}{i}", strength=-0.008 * (i + base), asof=asof, start=start, side="away"),
                    "home_score": home_score, "away_score": away_score,
                    "spread_line": -3.5, "total_line": 45.5,
                    "home_spread_odds": -110, "away_spread_odds": -110,
                    "over_odds": -110, "under_odds": -110,
                })
        return rows

    def test_candidate_supports_independent_alphas_and_normalizes_replay_count(self):
        rows = self._rows()
        model = fit_nfl_m2_v2c_candidate(rows[:24], margin_ridge_alpha=1.0, total_ridge_alpha=30.0)
        self.assertEqual(model.model_id, NFL_M2_V2C_CANDIDATE_MODEL_ID)
        self.assertEqual(model.margin_ridge_alpha, 1.0)
        self.assertEqual(model.total_ridge_alpha, 30.0)
        distribution = derive_nfl_m2_v2c_score_distribution(model, rows[24])
        self.assertEqual(len(distribution), len(model.residual_pairs))
        self.assertTrue(all(int(row["home_score"]) >= 0 and int(row["away_score"]) >= 0 for row in distribution))

    def test_selector_is_market_blind(self):
        rows = self._rows()
        baseline = select_nfl_m2_v2c_alphas(rows, alpha_grid=(1.0, 10.0, 30.0))
        changed = copy.deepcopy(rows)
        for row in changed:
            row["spread_line"] = 88.5
            row["total_line"] = 999.5
            row["home_spread_odds"] = -10000
            row["sportsbook"] = "FORBIDDEN_INPUT"
        observed = select_nfl_m2_v2c_alphas(changed, alpha_grid=(1.0, 10.0, 30.0))
        keys = ("selected_margin_ridge_alpha", "selected_total_ridge_alpha", "margin_scores", "total_scores")
        self.assertEqual(tuple(baseline[key] for key in keys), tuple(observed[key] for key in keys))
        self.assertFalse(observed["market_data_used"])

    def test_outer_heldout_mutation_cannot_change_training_only_selection(self):
        rows = self._rows()
        outer_train = [row for row in rows if row["season"] <= 2023]
        baseline = select_nfl_m2_v2c_alphas(outer_train, alpha_grid=(1.0, 10.0, 30.0))
        changed_all = copy.deepcopy(rows)
        for row in changed_all:
            if row["season"] == 2024:
                row["home_score"] = 70
                row["away_score"] = 0
        changed_outer_train = [row for row in changed_all if row["season"] <= 2023]
        observed = select_nfl_m2_v2c_alphas(changed_outer_train, alpha_grid=(1.0, 10.0, 30.0))
        self.assertEqual(baseline, observed)
        self.assertNotIn(2024, baseline["inner_test_seasons"])
        self.assertNotIn(2024, baseline["outer_training_seasons"])

    def test_outer_heldout_outcomes_cannot_change_same_fold_probabilities_or_alphas(self):
        rows = self._rows()
        kwargs = {"min_train_seasons": 2, "alpha_grid": (1.0, 10.0, 30.0)}
        baseline = build_nfl_m2_v2c_raw_evaluations(rows, **kwargs)
        first_test_season = min(int(row["season"]) for row in baseline)
        changed = copy.deepcopy(rows)
        for row in changed:
            if int(row["season"]) == first_test_season:
                row["home_score"] = 70
                row["away_score"] = 0
        observed = build_nfl_m2_v2c_raw_evaluations(changed, **kwargs)
        keys = (
            "game_id",
            "margin_ridge_alpha",
            "total_ridge_alpha",
            "m2_home_cover_prob",
            "m2_over_prob",
            "candidate_signed_key_probability",
        )
        left = [tuple(row[key] for key in keys) for row in baseline if int(row["season"]) == first_test_season]
        right = [tuple(row[key] for key in keys) for row in observed if int(row["season"]) == first_test_season]
        self.assertEqual(left, right)

    def test_market_mutation_cannot_change_selected_alphas_or_score_distribution_readouts(self):
        rows = self._rows()
        kwargs = {"min_train_seasons": 2, "alpha_grid": (1.0, 10.0, 30.0)}
        baseline = build_nfl_m2_v2c_raw_evaluations(rows, **kwargs)
        changed = copy.deepcopy(rows)
        for row in changed:
            row["spread_line"] = 88.5
            row["total_line"] = 999.5
            row["home_spread_odds"] = -10000
            row["away_spread_odds"] = 9000
            row["over_odds"] = -10000
            row["under_odds"] = 9000
            row["sportsbook"] = "FORBIDDEN_INPUT"
        observed = build_nfl_m2_v2c_raw_evaluations(changed, **kwargs)
        invariant_keys = (
            "game_id",
            "margin_ridge_alpha",
            "total_ridge_alpha",
            "candidate_signed_key_probability",
        )
        self.assertEqual(
            [tuple(row[key] for key in invariant_keys) for row in baseline],
            [tuple(row[key] for key in invariant_keys) for row in observed],
        )


if __name__ == "__main__":
    unittest.main()
