import math
import unittest

from sportsedge.core.promotion.football_registry import build_nfl_promotion_registry
from sportsedge.sports.nfl.m2 import NFL_M2_FEATURE_CONTRACT, PRODUCTION_NFL_M2_MODEL_ID


class NFLPromotionNumericIntegrityTests(unittest.TestCase):
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

    def _build(self, *, history=None, clv=None):
        return build_nfl_promotion_registry(
            self._math(),
            history or self._history(),
            declared_markets=["spread"],
            ci_attested=True,
            ci_attestation=self._ci(),
            clv_evidence=clv,
        )

    def test_calibration_pass_flag_cannot_disagree_with_passing_metrics(self):
        history = self._history()
        history["promotion_evidence"]["spread"]["calibration"]["pass"] = False
        with self.assertRaisesRegex(ValueError, "NFL_CALIBRATION_PASS_CONTRADICTION:spread"):
            self._build(history=history)

    def test_nonfinite_calibration_metric_fails_closed(self):
        history = self._history()
        history["promotion_evidence"]["spread"]["calibration"]["max_bin_deviation"] = math.nan
        with self.assertRaisesRegex(ValueError, "NFL_CALIBRATION_EVIDENCE_INVALID:spread"):
            self._build(history=history)

    def test_nan_mean_clv_cannot_promote(self):
        clv = self._clv()
        clv["markets"]["spread"]["mean_clv"] = math.nan
        with self.assertRaisesRegex(ValueError, "NFL_CLV_OFFICIAL_MEAN_CLV_INVALID:spread"):
            self._build(clv=clv)

    def test_infinite_clv_t_stat_cannot_promote(self):
        clv = self._clv()
        clv["markets"]["spread"]["clv_t_stat"] = math.inf
        with self.assertRaisesRegex(ValueError, "NFL_CLV_OFFICIAL_T_STAT_INVALID:spread"):
            self._build(clv=clv)

    def test_beat_close_rate_must_be_a_probability(self):
        clv = self._clv()
        clv["markets"]["spread"]["beat_close_rate"] = 1.2
        with self.assertRaisesRegex(ValueError, "NFL_CLV_OFFICIAL_BEAT_CLOSE_RATE_INVALID:spread"):
            self._build(clv=clv)


if __name__ == "__main__":
    unittest.main()
