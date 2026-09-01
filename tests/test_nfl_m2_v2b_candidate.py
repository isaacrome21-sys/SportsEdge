import copy
import unittest

from sportsedge.sports.nfl.m2 import PRODUCTION_NFL_M2_MODEL_ID, build_nfl_m2_features
from sportsedge.sports.nfl.m2_v2_candidate import price_nfl_m2_v2_game_markets
from sportsedge.sports.nfl.m2_v2b_candidate import (
    NFL_M2_V2B_CANDIDATE_MODEL_ID,
    NFL_M2_V2B_DISTRIBUTION_CONTRACT,
    derive_nfl_m2_v2b_score_distribution,
    fit_nfl_m2_v2b_candidate,
)
from sportsedge.sports.nfl.m2_v2b_validation import build_nfl_m2_v2b_raw_evaluations


class NFLM2V2BCandidateTests(unittest.TestCase):
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
        scores = [(24, 21), (27, 20), (20, 17), (31, 24), (23, 20), (28, 21), (17, 20), (21, 28)]
        rows = []
        for season in range(2018, 2025):
            for i in range(8):
                hs = 0.015 * (i + 1) + 0.002 * (season - 2018)
                aw = -0.012 * (i + 1) + 0.001 * (season - 2018)
                start = f"{season}-09-{10 + i:02d}T17:00:00+00:00"
                asof = f"{season}-09-{9 + i:02d}T17:00:00+00:00"
                home_score, away_score = scores[(season + i) % len(scores)]
                rows.append({
                    "game_id": f"{season}_{i}", "season": season, "week": i + 1,
                    "home_features": self._features(qb=f"H{season}{i}", strength=hs, asof=asof, start=start, side="home"),
                    "away_features": self._features(qb=f"A{season}{i}", strength=aw, asof=asof, start=start, side="away"),
                    "home_score": home_score, "away_score": away_score,
                    "spread_line": 3.5 if i % 2 == 0 else -2.5,
                    "total_line": 44.5 if i % 2 == 0 else 47.5,
                    "home_spread_odds": -110, "away_spread_odds": -110,
                    "over_odds": -110, "under_odds": -110,
                })
        return rows

    def test_v2b_has_new_identity_and_only_empirical_integer_score_support(self):
        train = self._rows()[:24]
        model = fit_nfl_m2_v2b_candidate(train, ridge_alpha=2.0)
        self.assertEqual(model.model_id, NFL_M2_V2B_CANDIDATE_MODEL_ID)
        self.assertNotEqual(model.model_id, PRODUCTION_NFL_M2_MODEL_ID)
        self.assertEqual(model.distribution_contract, NFL_M2_V2B_DISTRIBUTION_CONTRACT)
        observed = {(row["home_score"], row["away_score"]) for row in train}
        support = {(row.home_score, row.away_score) for row in model.empirical_scores}
        self.assertEqual(support, observed)
        self.assertEqual(sum(row.count for row in model.empirical_scores), len(train))

    def test_distribution_normalizes_and_key_mass_emerges_without_special_weights(self):
        rows = self._rows()
        model = fit_nfl_m2_v2b_candidate(rows[:24], ridge_alpha=2.0)
        distribution = derive_nfl_m2_v2b_score_distribution(model, rows[24])
        self.assertAlmostEqual(sum(float(row["weight"]) for row in distribution), 1.0)
        self.assertGreater(
            sum(float(row["weight"]) for row in distribution if abs(int(row["margin"])) in {3, 7}),
            0.0,
        )

    def test_root_market_mutation_cannot_change_v2b_distribution(self):
        rows = self._rows()
        train = rows[:24]
        target = rows[24]
        baseline = derive_nfl_m2_v2b_score_distribution(
            fit_nfl_m2_v2b_candidate(train, ridge_alpha=2.0), target
        )
        changed_train = copy.deepcopy(train)
        changed_target = copy.deepcopy(target)
        for row in changed_train:
            row["spread_line"] = 88.5
            row["total_line"] = 999.5
            row["home_spread_odds"] = -10000
            row["sportsbook"] = "FORBIDDEN_INPUT"
        changed_target["spread_line"] = -55.5
        changed_target["total_line"] = 10.5
        changed = derive_nfl_m2_v2b_score_distribution(
            fit_nfl_m2_v2b_candidate(changed_train, ridge_alpha=2.0), changed_target
        )
        self.assertEqual(baseline, changed)

    def test_market_thresholds_apply_after_v2b_distribution(self):
        rows = self._rows()
        model = fit_nfl_m2_v2b_candidate(rows[:24], ridge_alpha=2.0)
        distribution = derive_nfl_m2_v2b_score_distribution(model, rows[24])
        first = price_nfl_m2_v2_game_markets(distribution, spread_line=-3.5, total_line=41.5)
        second = price_nfl_m2_v2_game_markets(distribution, spread_line=7.5, total_line=55.5)
        self.assertEqual(first["moneyline"], second["moneyline"])
        self.assertNotEqual(first["spread"], second["spread"])
        self.assertNotEqual(first["total"], second["total"])

    def test_heldout_outcome_mutation_cannot_change_same_fold_v2b_probabilities(self):
        rows = self._rows()
        baseline = build_nfl_m2_v2b_raw_evaluations(rows, min_train_seasons=2, ridge_alpha=2.0)
        first_test = min(row["season"] for row in baseline)
        changed_rows = copy.deepcopy(rows)
        for row in changed_rows:
            if row["season"] == first_test:
                row["home_score"] = 70
                row["away_score"] = 0
        changed = build_nfl_m2_v2b_raw_evaluations(changed_rows, min_train_seasons=2, ridge_alpha=2.0)
        left = [row for row in baseline if row["season"] == first_test]
        right = [row for row in changed if row["season"] == first_test]
        keys = ("game_id", "m2_home_cover_prob", "m2_over_prob", "candidate_signed_key_probability")
        self.assertEqual(
            [tuple(row[key] for key in keys) for row in left],
            [tuple(row[key] for key in keys) for row in right],
        )


if __name__ == "__main__":
    unittest.main()
