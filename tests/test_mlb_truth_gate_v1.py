from __future__ import annotations

import unittest
from dataclasses import replace

from sportsedge.mlb_truth_gate_v1 import MLBTruthGateEvidence, MLBTruthGateError, evaluate_mlb_truth_gate_v1


def passing(market_id="MONEYLINE", market_family="V7_GAME"):
    return MLBTruthGateEvidence(
        market_id=market_id,
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
    def test_complete_evidence_can_pass_one_market(self):
        result = evaluate_mlb_truth_gate_v1(passing("MONEYLINE", "V7_GAME"))
        self.assertEqual(result.status, "OFFICIAL")
        self.assertEqual(result.market_id, "MONEYLINE")

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
            evaluate_mlb_truth_gate_v1(passing("MONEYLINE", "CFB_SPREAD"))

    def test_market_id_is_required_even_when_family_is_valid(self):
        with self.assertRaisesRegex(MLBTruthGateError, "CANONICAL_MARKET_ID_REQUIRED"):
            evaluate_mlb_truth_gate_v1(passing("", "V7_GAME"))

    def test_sibling_market_requires_separate_evidence_object(self):
        ml = evaluate_mlb_truth_gate_v1(passing("MONEYLINE", "V7_GAME"))
        total = evaluate_mlb_truth_gate_v1(passing("TOTALS", "V7_GAME"))
        self.assertEqual(ml.status, "OFFICIAL")
        self.assertEqual(total.status, "OFFICIAL")
        self.assertNotEqual(ml.market_id, total.market_id)
        # The evaluator exposes no family-level OFFICIAL result that could be inherited.
        self.assertFalse(hasattr(ml, "family_official"))


if __name__ == "__main__":
    unittest.main()
