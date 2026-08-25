import unittest

from sportsedge.core.promotion.nfl_external_deployment import (
    build_externally_attested_nfl_registry,
)
from sportsedge.core.validation.nfl_forward_clv_attestation import canonical_clv_payload_sha256
from sportsedge.sports.nfl.m2 import NFL_M2_FEATURE_CONTRACT, PRODUCTION_NFL_M2_MODEL_ID


class NFLExternalDeploymentBridgeTests(unittest.TestCase):
    def _math(self):
        return {
            "provenance": "REAL_PUBLIC_HISTORY",
            "source_sha256": "a" * 64,
            "code_git_sha": "1" * 40,
            "profile_version": "nfl-key-emergent-v3",
            "key_number_contract": "EMERGENT_VALIDATION_TARGET_V1",
            "seasons": [2018, 2019, 2020, 2021, 2022, 2023],
            "key_numbers": [-7, -3, 3, 7],
            "per_key_abs_error": {"-7": 0.002, "-3": 0.003, "3": 0.002, "7": 0.004},
            "max_allowed_abs_error": 0.005,
        }

    def _history(self):
        return {
            "provenance": "REAL_PUBLIC_HISTORY",
            "source_sha256": "a" * 64,
            "source_manifest_sha256": "a" * 64,
            "code_git_sha": "1" * 40,
            "model_id": PRODUCTION_NFL_M2_MODEL_ID,
            "feature_contract": NFL_M2_FEATURE_CONTRACT,
            "promotion_evidence": {
                "spread": {
                    "fold_wins": 7,
                    "fold_total": 10,
                    "fold_win_rate": 0.7,
                    "calibration": {"pass": True, "max_bin_deviation": 0.03, "threshold": 0.05},
                }
            },
        }

    def _ci(self):
        return {
            "schema_version": 1,
            "workflow_name": "football-nfl-promotion-evidence",
            "workflow_conclusion": "success",
            "workflow_run_id": 123,
            "git_sha": "1" * 40,
            "source_manifest_sha256": "a" * 64,
            "model_id": PRODUCTION_NFL_M2_MODEL_ID,
            "feature_contract": NFL_M2_FEATURE_CONTRACT,
            "verified_artifact_count": 7,
        }

    def _clv(self):
        return {
            "schema_version": 4,
            "sport": "nfl",
            "model_id": PRODUCTION_NFL_M2_MODEL_ID,
            "feature_contract": NFL_M2_FEATURE_CONTRACT,
            "code_git_sha": "1" * 40,
            "decision_log_sha256": "c" * 64,
            "close_log_sha256": "d" * 64,
            "decision_count": 200,
            "close_count": 200,
            "unique_observation_count": 200,
            "clv_probability_reference": "DECISION_THRESHOLD",
            "forward_time_contract": "PREGAME_DECISION_TO_PREGAME_CLOSE",
            "close_book_contract": "SAME_BOOK_AS_DECISION",
            "markets": {
                "spread": {
                    "logged_plays": 200,
                    "mean_clv": 0.005,
                    "clv_t_stat": 2.5,
                    "beat_close_rate": 0.56,
                }
            },
            "rejected_markets": {},
        }

    def _clv_attestation(self, clv):
        return {
            "schema_version": 1,
            "collector_contract": "NFL_FORWARD_CLV_COLLECTION_V1",
            "workflow_name": "football-nfl-forward-clv-collection",
            "workflow_conclusion": "success",
            "workflow_event": "schedule",
            "workflow_head_branch": "main",
            "workflow_run_id": 456,
            "git_sha": "1" * 40,
            "model_id": PRODUCTION_NFL_M2_MODEL_ID,
            "feature_contract": NFL_M2_FEATURE_CONTRACT,
            "decision_log_sha256": clv["decision_log_sha256"],
            "close_log_sha256": clv["close_log_sha256"],
            "clv_payload_sha256": canonical_clv_payload_sha256(clv),
            "decision_count": 200,
            "close_count": 200,
            "unique_observation_count": 200,
            "verified_artifact_count": 4,
        }

    def test_all_external_evidence_can_reach_deployed(self):
        clv = self._clv()
        registry = build_externally_attested_nfl_registry(
            self._math(), self._history(), declared_markets=["spread"],
            ci_attestation=self._ci(), clv_evidence=clv,
            clv_attestation=self._clv_attestation(clv),
        )
        self.assertEqual(registry["markets"]["spread"]["stage"], "DEPLOYED")
        self.assertEqual(registry["clv_attestation_state"], "EXTERNALLY_ATTESTED")

    def test_raw_clv_without_external_attestation_cannot_deploy(self):
        with self.assertRaisesRegex(ValueError, "NFL_FORWARD_CLV_ATTESTATION_REQUIRED"):
            build_externally_attested_nfl_registry(
                self._math(), self._history(), declared_markets=["spread"],
                ci_attestation=self._ci(), clv_evidence=self._clv(), clv_attestation=None,
            )

    def test_attestation_must_bind_exact_clv_payload(self):
        clv = self._clv()
        attestation = self._clv_attestation(clv)
        clv["markets"]["spread"]["mean_clv"] = 0.02
        with self.assertRaisesRegex(ValueError, "NFL_FORWARD_CLV_PAYLOAD_MISMATCH"):
            build_externally_attested_nfl_registry(
                self._math(), self._history(), declared_markets=["spread"],
                ci_attestation=self._ci(), clv_evidence=clv, clv_attestation=attestation,
            )

    def test_attestation_must_bind_logs_counts_and_code(self):
        clv = self._clv()
        for field, value, error in (
            ("decision_log_sha256", "e" * 64, "NFL_FORWARD_CLV_DECISION_LOG_MISMATCH"),
            ("unique_observation_count", 199, "NFL_FORWARD_CLV_UNIQUE_COUNT_MISMATCH"),
            ("git_sha", "2" * 40, "NFL_FORWARD_CLV_CODE_SHA_MISMATCH"),
        ):
            attestation = self._clv_attestation(clv)
            attestation[field] = value
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, error):
                    build_externally_attested_nfl_registry(
                        self._math(), self._history(), declared_markets=["spread"],
                        ci_attestation=self._ci(), clv_evidence=clv, clv_attestation=attestation,
                    )


if __name__ == "__main__":
    unittest.main()
