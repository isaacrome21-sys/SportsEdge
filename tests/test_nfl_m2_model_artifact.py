import unittest

from sportsedge.sports.nfl.m2 import NFLM2ScoreModel, NFL_M2_FEATURE_CONTRACT, PRODUCTION_NFL_M2_MODEL_ID
from sportsedge.sports.nfl.model_artifact import build_nfl_m2_model_artifact, load_nfl_m2_model_artifact


class NFLM2ModelArtifactTests(unittest.TestCase):
    def _model(self):
        return NFLM2ScoreModel(
            model_id=PRODUCTION_NFL_M2_MODEL_ID,
            feature_contract=NFL_M2_FEATURE_CONTRACT,
            feature_names=("home_adj_off_epa", "away_adj_off_epa"),
            feature_means=(0.1, -0.1),
            feature_scales=(1.0, 1.0),
            margin_coefficients=(1.0, 0.5, -0.5),
            total_coefficients=(44.0, 0.2, 0.2),
            train_seasons=(2022, 2023, 2024, 2025),
            ridge_alpha=10.0,
            margin_sigma=13.4,
            total_sigma=10.5,
            residual_correlation=0.1,
            residual_pairs=((1.0, 2.0), (-1.0, -2.0)),
        )

    def test_round_trip_preserves_exact_model_and_bindings(self):
        payload = build_nfl_m2_model_artifact(
            self._model(), code_git_sha="1" * 40, source_manifest_sha256="a" * 64
        )
        loaded = load_nfl_m2_model_artifact(
            payload, expected_code_git_sha="1" * 40, expected_source_manifest_sha256="a" * 64
        )
        self.assertEqual(loaded, self._model())
        self.assertEqual(payload["trained_through_season"], 2025)

    def test_wrong_code_or_source_binding_fails_closed(self):
        payload = build_nfl_m2_model_artifact(
            self._model(), code_git_sha="1" * 40, source_manifest_sha256="a" * 64
        )
        with self.assertRaisesRegex(ValueError, "NFL_M2_MODEL_ARTIFACT_CODE_SHA_MISMATCH"):
            load_nfl_m2_model_artifact(payload, expected_code_git_sha="2" * 40)
        with self.assertRaisesRegex(ValueError, "NFL_M2_MODEL_ARTIFACT_SOURCE_MISMATCH"):
            load_nfl_m2_model_artifact(payload, expected_source_manifest_sha256="b" * 64)

    def test_nonfinite_or_wrong_model_identity_is_rejected(self):
        payload = build_nfl_m2_model_artifact(
            self._model(), code_git_sha="1" * 40, source_manifest_sha256="a" * 64
        )
        payload["model"]["margin_sigma"] = float("nan")
        with self.assertRaisesRegex(ValueError, "NFL_M2_MODEL_ARTIFACT_NONFINITE"):
            load_nfl_m2_model_artifact(payload)
        payload = build_nfl_m2_model_artifact(
            self._model(), code_git_sha="1" * 40, source_manifest_sha256="a" * 64
        )
        payload["model_id"] = "other"
        with self.assertRaisesRegex(ValueError, "NFL_M2_MODEL_ARTIFACT_MODEL_ID_MISMATCH"):
            load_nfl_m2_model_artifact(payload)


if __name__ == "__main__":
    unittest.main()
