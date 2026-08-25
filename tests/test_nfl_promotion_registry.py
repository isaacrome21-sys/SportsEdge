import unittest

from sportsedge.core.promotion.football_registry import build_nfl_promotion_registry
from sportsedge.sports.nfl.m2 import NFL_M2_FEATURE_CONTRACT, PRODUCTION_NFL_M2_MODEL_ID


class NFLPromotionRegistryTests(unittest.TestCase):
    def _math(self, bad=False):
        return {
            "provenance": "REAL_PUBLIC_HISTORY",
            "source_sha256": "a" * 64,
            "profile_version": "nfl-key-emergent-v3",
            "key_number_contract": "EMERGENT_VALIDATION_TARGET_V1",
            "seasons": [2018, 2019, 2020, 2021, 2022, 2023],
            "key_numbers": [-7, -3, 3, 7],
            "per_key_abs_error": {"-7": 0.002, "-3": 0.003, "3": 0.009 if bad else 0.002, "7": 0.004},
            "max_allowed_abs_error": 0.005,
        }

    def _history(self, spread_wins=7, spread_total=10, calibration_pass=True):
        return {
            "provenance": "REAL_PUBLIC_HISTORY",
            "source_sha256": "a" * 64,
            "model_id": PRODUCTION_NFL_M2_MODEL_ID,
            "feature_contract": NFL_M2_FEATURE_CONTRACT,
            "promotion_evidence": {
                "spread": {
                    "fold_wins": spread_wins,
                    "fold_total": spread_total,
                    "fold_win_rate": spread_wins / spread_total,
                    "calibration": {
                        "pass": calibration_pass,
                        "max_bin_deviation": 0.03 if calibration_pass else 0.09,
                        "threshold": 0.05,
                    },
                },
                "total": {
                    "fold_wins": 4,
                    "fold_total": 10,
                    "fold_win_rate": 0.4,
                    "calibration": {"pass": True, "max_bin_deviation": 0.02, "threshold": 0.05},
                },
            },
        }

    def test_missing_market_evidence_never_inherits_another_market_promotion(self):
        registry = build_nfl_promotion_registry(
            self._math(), self._history(), declared_markets=["spread", "total", "passing_yards"]
        )
        self.assertEqual(registry["markets"]["passing_yards"]["stage"], "VALIDATED_MATH")
        self.assertFalse(registry["markets"]["passing_yards"]["eligible"])
        self.assertEqual(registry["markets"]["passing_yards"]["reason"], "WALKFORWARD_EVIDENCE_MISSING")

    def test_fold_gate_is_per_market(self):
        registry = build_nfl_promotion_registry(
            self._math(), self._history(), declared_markets=["spread", "total"]
        )
        self.assertEqual(registry["markets"]["spread"]["stage"], "PRODUCTION_LOGIC_PASS")
        self.assertEqual(registry["markets"]["total"]["stage"], "VALIDATED_MATH")

    def test_ci_attestation_and_calibration_are_both_required_for_ci_stage(self):
        no_ci = build_nfl_promotion_registry(
            self._math(), self._history(), declared_markets=["spread"], ci_attested=False
        )
        self.assertEqual(no_ci["markets"]["spread"]["stage"], "PRODUCTION_LOGIC_PASS")
        with_ci = build_nfl_promotion_registry(
            self._math(), self._history(), declared_markets=["spread"], ci_attested=True
        )
        self.assertEqual(with_ci["markets"]["spread"]["stage"], "CI_ATTESTED")
        bad_cal = build_nfl_promotion_registry(
            self._math(), self._history(calibration_pass=False), declared_markets=["spread"], ci_attested=True
        )
        self.assertEqual(bad_cal["markets"]["spread"]["stage"], "PRODUCTION_LOGIC_PASS")

    def test_deployment_requires_real_clv_sample_gate(self):
        base = build_nfl_promotion_registry(
            self._math(), self._history(), declared_markets=["spread"], ci_attested=True,
            clv_evidence={"spread": {"logged_plays": 199, "mean_clv": 0.02, "clv_t_stat": 3.0}},
        )
        self.assertEqual(base["markets"]["spread"]["stage"], "CI_ATTESTED")
        passed = build_nfl_promotion_registry(
            self._math(), self._history(), declared_markets=["spread"], ci_attested=True,
            clv_evidence={"spread": {"logged_plays": 200, "mean_clv": 0.001, "clv_t_stat": 2.01}},
        )
        self.assertEqual(passed["markets"]["spread"]["stage"], "DEPLOYED")
        self.assertTrue(passed["markets"]["spread"]["eligible"])

    def test_source_hash_mismatch_fails_closed_before_any_market_evaluation(self):
        history = self._history()
        history["source_sha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "NFL_PROMOTION_SOURCE_HASH_MISMATCH"):
            build_nfl_promotion_registry(self._math(), history, declared_markets=["spread"])

    def test_schedule_only_challenger_cannot_promote_production_m2(self):
        history = self._history()
        history["model_id"] = "nfl_schedule_score_challenger_v1"
        with self.assertRaisesRegex(ValueError, "NFL_PROMOTION_MODEL_ID_MISMATCH"):
            build_nfl_promotion_registry(self._math(), history, declared_markets=["spread"])

    def test_wrong_feature_contract_cannot_promote_production_m2(self):
        history = self._history()
        history["feature_contract"] = "SCHEDULE_ONLY"
        with self.assertRaisesRegex(ValueError, "NFL_PROMOTION_FEATURE_CONTRACT_MISMATCH"):
            build_nfl_promotion_registry(self._math(), history, declared_markets=["spread"])

    def test_bad_math_blocks_every_market(self):
        registry = build_nfl_promotion_registry(
            self._math(bad=True), self._history(), declared_markets=["spread", "total"]
        )
        self.assertTrue(all(row["stage"] == "BLOCKED_MATH" for row in registry["markets"].values()))
        self.assertTrue(all(row["eligible"] is False for row in registry["markets"].values()))


if __name__ == "__main__":
    unittest.main()
