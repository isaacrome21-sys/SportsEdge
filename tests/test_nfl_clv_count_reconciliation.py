import unittest

from sportsedge.core.promotion.football_registry import build_nfl_promotion_registry
from sportsedge.sports.nfl.m2 import NFL_M2_FEATURE_CONTRACT, PRODUCTION_NFL_M2_MODEL_ID


class NFLCLVCountReconciliationTests(unittest.TestCase):
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
            "workflow_run_id": 12345,
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
                    "mean_clv": 0.001,
                    "clv_t_stat": 2.01,
                    "beat_close_rate": 0.55,
                }
            },
            "rejected_markets": {},
        }

    def _build(self, clv):
        return build_nfl_promotion_registry(
            self._math(),
            self._history(),
            declared_markets=["spread"],
            ci_attested=True,
            ci_attestation=self._ci(),
            clv_evidence=clv,
        )

    def test_consistent_counts_allow_the_existing_deployment_gate(self):
        registry = self._build(self._clv())
        self.assertEqual(registry["markets"]["spread"]["stage"], "DEPLOYED")

    def test_decision_and_close_counts_must_match(self):
        clv = self._clv()
        clv["close_count"] = 199
        with self.assertRaisesRegex(ValueError, "NFL_CLV_DECISION_CLOSE_COUNT_MISMATCH"):
            self._build(clv)

    def test_unique_observation_count_must_match_paired_rows(self):
        clv = self._clv()
        clv["unique_observation_count"] = 199
        with self.assertRaisesRegex(ValueError, "NFL_CLV_UNIQUE_OBSERVATION_COUNT_MISMATCH"):
            self._build(clv)

    def test_market_summaries_cannot_claim_more_plays_than_the_logs(self):
        clv = self._clv()
        clv["markets"]["spread"]["logged_plays"] = 201
        with self.assertRaisesRegex(ValueError, "NFL_CLV_MARKET_COUNT_MISMATCH"):
            self._build(clv)

    def test_rejected_rows_are_included_in_total_observation_reconciliation(self):
        clv = self._clv()
        clv["decision_count"] = 210
        clv["close_count"] = 210
        clv["unique_observation_count"] = 210
        clv["rejected_markets"] = {
            "total": {
                "logged_plays": 10,
                "mean_clv": -0.002,
                "clv_t_stat": -0.5,
                "beat_close_rate": 0.4,
            }
        }
        registry = self._build(clv)
        self.assertEqual(registry["markets"]["spread"]["stage"], "DEPLOYED")
        self.assertEqual(registry["clv_log_identity"]["unique_observation_count"], 210)

    def test_schema_four_requires_explicit_rejected_market_bucket(self):
        clv = self._clv()
        del clv["rejected_markets"]
        with self.assertRaisesRegex(ValueError, "NFL_CLV_REJECTED_MARKETS_REQUIRED"):
            self._build(clv)


if __name__ == "__main__":
    unittest.main()
