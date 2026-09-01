import copy
import unittest

from sportsedge.sports.nfl.m2 import (
    PRODUCTION_NFL_M2_MODEL_ID,
    build_nfl_m2_features,
)
from sportsedge.sports.nfl.m2_v2_candidate import (
    NFL_M2_V2_CANDIDATE_MODEL_ID,
    NFL_M2_V2_DISTRIBUTION_CONTRACT,
    derive_nfl_m2_v2_score_distribution,
    fit_nfl_m2_v2_candidate,
    price_nfl_m2_v2_game_markets,
)
from sportsedge.sports.nfl.m2_v2_validation import (
    build_nfl_m2_v2_candidate_evidence,
    build_nfl_m2_v2_raw_evaluations,
)


class NFLM2V2CandidateTests(unittest.TestCase):
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
        score_pairs = [
            (24, 21), (27, 20), (20, 17), (31, 24),
            (23, 20), (28, 21), (17, 20), (21, 28),
        ]
        rows = []
        for season in range(2018, 2025):
            for i in range(8):
                home_strength = 0.015 * (i + 1) + 0.002 * (season - 2018)
                away_strength = -0.012 * (i + 1) + 0.001 * (season - 2018)
                start = f"{season}-09-{10 + i:02d}T17:00:00+00:00"
                asof = f"{season}-09-{9 + i:02d}T17:00:00+00:00"
                home_score, away_score = score_pairs[(i + season) % len(score_pairs)]
                rows.append({
                    "game_id": f"{season}_{i}",
                    "season": season,
                    "week": i + 1,
                    "home_features": self._features(
                        qb=f"H_{season}_{i}", strength=home_strength,
                        asof=asof, start=start, side="home",
                    ),
                    "away_features": self._features(
                        qb=f"A_{season}_{i}", strength=away_strength,
                        asof=asof, start=start, side="away",
                    ),
                    "home_score": home_score,
                    "away_score": away_score,
                    "spread_line": 3.5 if i % 2 == 0 else -2.5,
                    "total_line": 44.5 if i % 2 == 0 else 47.5,
                    "home_spread_odds": -110,
                    "away_spread_odds": -110,
                    "over_odds": -110,
                    "under_odds": -110,
                })
        return rows

    def test_candidate_identity_is_separate_and_support_is_observed_integer_scores(self):
        train = self._rows()[:24]
        model = fit_nfl_m2_v2_candidate(train, ridge_alpha=2.0)
        self.assertEqual(model.model_id, NFL_M2_V2_CANDIDATE_MODEL_ID)
        self.assertNotEqual(model.model_id, PRODUCTION_NFL_M2_MODEL_ID)
        self.assertEqual(model.distribution_contract, NFL_M2_V2_DISTRIBUTION_CONTRACT)
        observed = {(int(row["home_score"]), int(row["away_score"])) for row in train}
        support = {(point.home_score, point.away_score) for point in model.support_points}
        self.assertTrue(support.issubset(observed))
        self.assertTrue(all(isinstance(point.home_score, int) and isinstance(point.away_score, int) for point in model.support_points))

    def test_distribution_is_normalized_and_contains_only_training_score_pairs(self):
        rows = self._rows()
        train = rows[:24]
        model = fit_nfl_m2_v2_candidate(train, ridge_alpha=2.0)
        distribution = derive_nfl_m2_v2_score_distribution(model, rows[24])
        observed = {(row["home_score"], row["away_score"]) for row in train}
        self.assertAlmostEqual(sum(float(row["weight"]) for row in distribution), 1.0)
        self.assertTrue({(row["home_score"], row["away_score"]) for row in distribution}.issubset(observed))
        # This support includes real key-number outcomes naturally; no special key
        # mass is added anywhere in the candidate implementation.
        key_mass = sum(float(row["weight"]) for row in distribution if abs(int(row["margin"])) in {3, 7})
        self.assertGreater(key_mass, 0.0)

    def test_root_market_fields_cannot_change_candidate_distribution(self):
        rows = self._rows()
        train = rows[:24]
        target = rows[24]
        baseline = derive_nfl_m2_v2_score_distribution(
            fit_nfl_m2_v2_candidate(train, ridge_alpha=2.0), target
        )
        changed_train = copy.deepcopy(train)
        changed_target = copy.deepcopy(target)
        for row in changed_train:
            row["spread_line"] = 99.5
            row["total_line"] = 999.5
            row["home_spread_odds"] = -10000
            row["book"] = "MUST_NOT_ENTER_CANDIDATE"
        changed_target["spread_line"] = -77.5
        changed_target["total_line"] = 12.5
        changed = derive_nfl_m2_v2_score_distribution(
            fit_nfl_m2_v2_candidate(changed_train, ridge_alpha=2.0), changed_target
        )
        self.assertEqual(baseline, changed)

    def test_market_lines_are_post_distribution_readouts_only(self):
        rows = self._rows()
        model = fit_nfl_m2_v2_candidate(rows[:24], ridge_alpha=2.0)
        distribution = derive_nfl_m2_v2_score_distribution(model, rows[24])
        first = price_nfl_m2_v2_game_markets(distribution, spread_line=-3.5, total_line=41.5)
        second = price_nfl_m2_v2_game_markets(distribution, spread_line=7.5, total_line=55.5)
        self.assertEqual(first["moneyline"], second["moneyline"])
        self.assertNotEqual(first["spread"], second["spread"])
        self.assertNotEqual(first["total"], second["total"])
        self.assertAlmostEqual(sum(first["spread"].values()), 1.0)
        self.assertAlmostEqual(sum(first["total"].values()), 1.0)

    def test_heldout_outcomes_cannot_change_same_fold_candidate_probabilities(self):
        rows = self._rows()
        baseline = build_nfl_m2_v2_raw_evaluations(rows, min_train_seasons=2, ridge_alpha=2.0)
        first_test = min(row["season"] for row in baseline)
        mutated = copy.deepcopy(rows)
        for row in mutated:
            if row["season"] == first_test:
                row["home_score"] = 70
                row["away_score"] = 0
        changed = build_nfl_m2_v2_raw_evaluations(mutated, min_train_seasons=2, ridge_alpha=2.0)
        left = [row for row in baseline if row["season"] == first_test]
        right = [row for row in changed if row["season"] == first_test]
        keys = (
            "game_id", "m2_home_cover_prob", "m2_over_prob",
            "candidate_signed_key_probability", "support_point_count",
        )
        self.assertEqual(
            [tuple(row[key] for key in keys) for row in left],
            [tuple(row[key] for key in keys) for row in right],
        )

    def test_full_evidence_is_diagnostic_only_and_uses_same_fold_threshold(self):
        evidence = build_nfl_m2_v2_candidate_evidence(
            self._rows(),
            source_manifest_sha256="a" * 64,
            min_train_seasons=2,
            min_calibration_fit_seasons=2,
            calibration_min_bin_n=1,
            ridge_alpha=2.0,
        )
        self.assertEqual(evidence["status"], "DIAGNOSTIC_CANDIDATE_ONLY")
        self.assertFalse(evidence["promotion_eligible"])
        self.assertEqual(evidence["model_id"], NFL_M2_V2_CANDIDATE_MODEL_ID)
        self.assertTrue(evidence["folds"])
        self.assertGreater(evidence["candidate_distribution_profile"]["heldout_game_count"], 0)
        for market in ("spread", "total"):
            self.assertEqual(evidence["candidate_historical_evidence"][market]["required_fold_win_rate"], 0.65)

    def test_fractional_training_scores_are_rejected_instead_of_rounded(self):
        rows = self._rows()[:24]
        rows[0]["home_score"] = 24.5
        with self.assertRaisesRegex(ValueError, "NFL_M2_V2_HOME_SCORE_INTEGER_REQUIRED"):
            fit_nfl_m2_v2_candidate(rows)


if __name__ == "__main__":
    unittest.main()
