import unittest

from sportsedge.sports.cfb.truth_gate import (
    CFBTruthGateError,
    cfb_candidate_meets_edge_floor,
    evaluate_cfb_truth_gate,
)


_SHA = "a" * 64


def _evidence(**overrides):
    payload = {
        "pit_holdout_valid": True,
        "temporal_leakage_check_passed": True,
        "model_artifact_bound": True,
        "source_evidence_bound": True,
        "paired_market_evidence_bound": True,
        "settlement_evidence_complete": True,
        "model_artifact_sha256": _SHA,
        "source_manifest_sha256": "b" * 64,
        "validation_report_sha256": "c" * 64,
        "market_evidence_sha256": "d" * 64,
        "evidence_rows": 200,
        "calibration_slope": 1.0,
        "calibration_intercept": 0.0,
        "ece": 0.02,
        "mean_clv": 0.005,
        "after_vig_roi": 0.02,
    }
    payload.update(overrides)
    return payload


class TestCFBTruthGate(unittest.TestCase):
    def test_complete_evidence_can_pass_without_mutating_governance(self):
        result = evaluate_cfb_truth_gate(_evidence())
        self.assertTrue(result.passes)
        self.assertEqual(result.status, "PASS")
        output = result.to_dict()
        self.assertFalse(output["governance"]["eligible_changed"])
        self.assertFalse(output["governance"]["model_p_created"])
        self.assertTrue(output["governance"]["candidate_edge_floor_is_separate"])

    def test_all_frozen_boundary_values_pass(self):
        for slope in (0.90, 1.10):
            with self.subTest(slope=slope):
                self.assertTrue(evaluate_cfb_truth_gate(_evidence(calibration_slope=slope)).passes)
        for intercept in (-0.03, 0.03):
            with self.subTest(intercept=intercept):
                self.assertTrue(evaluate_cfb_truth_gate(_evidence(calibration_intercept=intercept)).passes)
        self.assertTrue(evaluate_cfb_truth_gate(_evidence(ece=0.025)).passes)

    def test_each_empirical_gate_fails_closed(self):
        cases = {
            "evidence_rows": (199, "SAMPLE_DEPTH_BELOW_MINIMUM"),
            "calibration_slope": (0.899, "CALIBRATION_SLOPE_OUT_OF_RANGE"),
            "calibration_intercept": (0.031, "CALIBRATION_INTERCEPT_OUT_OF_RANGE"),
            "ece": (0.026, "ECE_OUT_OF_RANGE"),
            "mean_clv": (0.0049, "CLV_BELOW_MINIMUM"),
            "after_vig_roi": (0.0199, "AFTER_VIG_ROI_BELOW_MINIMUM"),
        }
        for field, (value, expected) in cases.items():
            with self.subTest(field=field):
                result = evaluate_cfb_truth_gate(_evidence(**{field: value}))
                self.assertFalse(result.passes)
                self.assertIn(expected, result.failures)

    def test_provenance_and_pit_booleans_are_required_true(self):
        cases = {
            "pit_holdout_valid": "PIT_HOLDOUT_INVALID",
            "temporal_leakage_check_passed": "TEMPORAL_LEAKAGE_CHECK_FAILED",
            "model_artifact_bound": "MODEL_ARTIFACT_UNBOUND",
            "source_evidence_bound": "SOURCE_EVIDENCE_UNBOUND",
            "paired_market_evidence_bound": "PAIRED_MARKET_EVIDENCE_UNBOUND",
            "settlement_evidence_complete": "SETTLEMENT_EVIDENCE_INCOMPLETE",
        }
        for field, expected in cases.items():
            with self.subTest(field=field):
                result = evaluate_cfb_truth_gate(_evidence(**{field: False}))
                self.assertIn(expected, result.failures)

    def test_missing_or_fake_summary_evidence_cannot_pass(self):
        missing = _evidence()
        missing.pop("market_evidence_sha256")
        with self.assertRaisesRegex(CFBTruthGateError, "SHA256_REQUIRED"):
            evaluate_cfb_truth_gate(missing)

        no_boolean = _evidence(pit_holdout_valid=1)
        with self.assertRaisesRegex(CFBTruthGateError, "BOOLEAN_REQUIRED"):
            evaluate_cfb_truth_gate(no_boolean)

    def test_negative_ece_fails(self):
        result = evaluate_cfb_truth_gate(_evidence(ece=-0.001))
        self.assertIn("ECE_OUT_OF_RANGE", result.failures)

    def test_edge_floor_is_separate_and_exact(self):
        self.assertTrue(cfb_candidate_meets_edge_floor(model_probability=0.55, no_vig_market_probability=0.52))
        self.assertFalse(cfb_candidate_meets_edge_floor(model_probability=0.5499, no_vig_market_probability=0.52))
        with self.assertRaises(CFBTruthGateError):
            cfb_candidate_meets_edge_floor(model_probability=1.01, no_vig_market_probability=0.52)


if __name__ == "__main__":
    unittest.main()
