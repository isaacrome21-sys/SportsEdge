from __future__ import annotations

import copy
import unittest

from sportsedge.sports.cfb.candidate_families import TEAM_METRIC_KEYS
from sportsedge.sports.cfb.candidate_model_v2 import candidate_feature_names
from sportsedge.sports.cfb.candidate_registry_v2 import EQUAL, RELIABILITY, BLEND, GAMES
from sportsedge.sports.cfb.selected_candidate_artifact import (
    CFBSelectedCandidateArtifactError,
    build_cfb_selected_candidate_artifact,
    load_cfb_selected_candidate_artifact,
)
from sportsedge.sports.cfb.selected_candidate_model import (
    fit_cfb_selected_candidate_score_model,
    simulate_cfb_selected_candidate_distribution,
)


def metrics(season: int, through_week: int, source: str, value: float, games: int):
    out = {key: float(value + idx * 0.003) for idx, key in enumerate(TEAM_METRIC_KEYS)}
    out.update({
        "team": "T",
        "season": season,
        "through_week": through_week,
        "sample_source": source,
        "games_in_sample": games,
    })
    return out


def make_row(i: int, *, week: int = 3):
    games = max(0, week - 1)
    prior_h = metrics(2025, 99, "PRIOR_SEASON_FALLBACK", 0.10 + i * 0.002, 0)
    prior_a = metrics(2025, 99, "PRIOR_SEASON_FALLBACK", 0.16 + i * 0.001, 0)
    if week == 1:
        current_h = copy.deepcopy(prior_h)
        current_a = copy.deepcopy(prior_a)
    else:
        current_h = metrics(2026, week - 1, "CURRENT_SEASON_PRIOR_WEEKS", 0.24 + i * 0.004, games)
        current_a = metrics(2026, week - 1, "CURRENT_SEASON_PRIOR_WEEKS", 0.20 + i * 0.003, games)
    row = {
        "season": 2026,
        "week": week,
        "neutral_site": bool(i % 5 == 0),
        "weather": {"game_indoor": True},
        "home_metrics": copy.deepcopy(current_h),
        "away_metrics": copy.deepcopy(current_a),
        "home_prior_metrics": prior_h,
        "away_prior_metrics": prior_a,
        "home_current_metrics": current_h,
        "away_current_metrics": current_a,
        "home_score": 20 + (i * 7) % 31,
        "away_score": 13 + (i * 5) % 28,
    }
    if i == 0:
        row.update({
            "regulation_home_score": 24,
            "regulation_away_score": 24,
            "home_score": 31,
            "away_score": 24,
        })
    return row


class TestCFBSelectedCandidateServing(unittest.TestCase):
    def setUp(self):
        self.rows = [make_row(i, week=1 if i < 4 else 3 + (i % 5)) for i in range(28)]
        self.live = make_row(40, week=6)
        self.sha_a = "a" * 64
        self.sha_b = "b" * 64
        self.sha_c = "c" * 64

    def test_all_four_families_roundtrip_without_prediction_drift(self):
        for family in (EQUAL, RELIABILITY, BLEND, GAMES):
            with self.subTest(family=family):
                model = fit_cfb_selected_candidate_score_model(self.rows, family=family, ridge_alpha=10.0)
                before = model.predict_means(self.live)
                artifact = build_cfb_selected_candidate_artifact(
                    model,
                    model_code_sha256=self.sha_a,
                    training_source_sha256=self.sha_b,
                    selection_result_sha256=self.sha_c,
                )
                loaded = load_cfb_selected_candidate_artifact(
                    artifact,
                    expected_model_code_sha256=self.sha_a,
                    expected_training_source_sha256=self.sha_b,
                    expected_selection_result_sha256=self.sha_c,
                )
                after = loaded.predict_means(self.live)
                self.assertEqual(before, after)
                self.assertEqual(loaded.family, family)
                self.assertEqual(loaded.feature_names, candidate_feature_names(family))

    def test_games_family_keeps_two_extra_features_through_artifact(self):
        model = fit_cfb_selected_candidate_score_model(self.rows, family=GAMES, ridge_alpha=10.0)
        artifact = build_cfb_selected_candidate_artifact(
            model,
            model_code_sha256=self.sha_a,
            training_source_sha256=self.sha_b,
            selection_result_sha256=self.sha_c,
        )
        loaded = load_cfb_selected_candidate_artifact(artifact)
        self.assertEqual(loaded.feature_names[-2:], (
            "home_games_in_sample_feature",
            "away_games_in_sample_feature",
        ))
        self.assertEqual(len(loaded.feature_names), len(candidate_feature_names(EQUAL)) + 2)

    def test_week1_is_executable_for_every_family(self):
        week1 = make_row(45, week=1)
        for family in (EQUAL, RELIABILITY, BLEND, GAMES):
            model = fit_cfb_selected_candidate_score_model(self.rows, family=family, ridge_alpha=10.0)
            home, away = model.predict_means(week1)
            self.assertIsInstance(home, float)
            self.assertIsInstance(away, float)

    def test_simulation_is_seed_deterministic_and_preserves_ot_resolution(self):
        model = fit_cfb_selected_candidate_score_model(self.rows, family=BLEND, ridge_alpha=10.0)
        first = simulate_cfb_selected_candidate_distribution(model, self.live, seed=20260918, n_paths=300)
        second = simulate_cfb_selected_candidate_distribution(model, self.live, seed=20260918, n_paths=300)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 300)
        self.assertTrue(all(row["home_score"] != row["away_score"] for row in first))

    def test_artifact_tamper_and_binding_mismatch_fail_closed(self):
        model = fit_cfb_selected_candidate_score_model(self.rows, family=RELIABILITY, ridge_alpha=10.0)
        artifact = build_cfb_selected_candidate_artifact(
            model,
            model_code_sha256=self.sha_a,
            training_source_sha256=self.sha_b,
            selection_result_sha256=self.sha_c,
        )
        with self.assertRaisesRegex(CFBSelectedCandidateArtifactError, "MODEL_CODE_SHA256_MISMATCH"):
            load_cfb_selected_candidate_artifact(artifact, expected_model_code_sha256="d" * 64)

        tampered = copy.deepcopy(artifact)
        tampered["candidate_family"] = GAMES
        with self.assertRaisesRegex(CFBSelectedCandidateArtifactError, "ARTIFACT_HASH_MISMATCH"):
            load_cfb_selected_candidate_artifact(tampered)

        authority = copy.deepcopy(artifact)
        authority["authority"]["official"] = True
        # Authority is checked before the artifact hash so even a recomputed wrapper cannot grant authority.
        with self.assertRaisesRegex(CFBSelectedCandidateArtifactError, "AUTHORITY_MUST_REMAIN_ZERO"):
            load_cfb_selected_candidate_artifact(authority)


if __name__ == "__main__":
    unittest.main()
