from __future__ import annotations

import unittest
from dataclasses import replace

from sportsedge.mlb_truth_gate_v1 import MLBTruthGateEvidence, MLBTruthGateError, evaluate_mlb_truth_gate_v1


def passing(market_family="V7_GAME"):
    return MLBTruthGateEvidence(
        market_family=market_family,
        forward_seasons=3,
        promoted_sample=250,
        season_fold_scoring_win_rate=0.67,
        brier_model=0.20,
        brier_novig_market=0.21,
        logloss_model=0.58,
        logloss_novig_market=0.60,
        mean_novig_clv=0.005,
        clv_tstat=2.2,
        roi_after_vig=0.01,
        calibration_slope=1.0,
        calibration_intercept=0.0,
        ece=0.02,
        recent_2season_deterioration=False,
        leakage_violations=0,
        pit_reproducible=True,
        policy_sha_valid=True,
        benchmark_methodology_sha_valid=True,
        model_code_sha_valid=True,
        feature_schema_sha_valid=True,
        structural_change_clearance=True,
        coherent_joint_constraints=True,
        all_promoted_rows_replayable=True,
    )


class MLBTruthGateTests(unittest.TestCase):
    def test_complete_evidence_can_pass(self):
        result = evaluate_mlb_truth_gate_v1(passing())
        self.assertEqual(result.status, "OFFICIAL")

    def test_zero_roi_and_missing_hashes_fail(self):
        result = evaluate_mlb_truth_gate_v1(replace(
            passing(),
            roi_after_vig=0.0,
            model_code_sha_valid=False,
            feature_schema_sha_valid=False,
        ))
        self.assertEqual(result.status, "FAILED")
        self.assertIn("ROI_AFTER_VIG_NOT_STRICTLY_POSITIVE", result.failures)
        self.assertIn("MODEL_CODE_SHA_INVALID", result.failures)
        self.assertIn("FEATURE_SCHEMA_SHA_INVALID", result.failures)

    def test_structural_change_revokes_certification_input(self):
        result = evaluate_mlb_truth_gate_v1(replace(passing(), structural_change_clearance=False))
        self.assertIn("STRUCTURAL_CHANGE_CLEARANCE_MISSING", result.failures)

    def test_unknown_market_family_cannot_inherit_certification(self):
        with self.assertRaisesRegex(MLBTruthGateError, "MARKET_FAMILY"):
            evaluate_mlb_truth_gate_v1(passing("CFB_SPREAD"))


if __name__ == "__main__":
    unittest.main()
