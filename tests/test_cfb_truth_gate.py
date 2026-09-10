import hashlib
import unittest

from sportsedge.sports.cfb.truth_gate import (
    CFB_TRUTH_GATE_POLICY_PATH,
    CFB_TRUTH_GATE_POLICY_SHA256,
    CFBTruthGate,
    CFBTruthGateError,
    cfb_candidate_meets_edge_floor,
    evaluate_cfb_truth_gate,
)


def _evidence(**overrides):
    payload = {
        "market": "SPREAD",
        "evidence_market": "SPREAD",
        "evidence_policy_sha256": CFB_TRUTH_GATE_POLICY_SHA256,
        "pit_reproducible": True,
        "paired_historical_price_evidence_complete": True,
        "recent_two_season_ok": True,
        "model_artifact_bound": True,
        "source_evidence_bound": True,
        "settlement_evidence_complete": True,
        "model_artifact_sha256": "a" * 64,
        "source_manifest_sha256": "b" * 64,
        "validation_report_sha256": "c" * 64,
        "market_evidence_sha256": "d" * 64,
        "leakage_violations": 0,
        "n_forward_seasons": 4,
        "n_promoted": 200,
        "brier_model": 0.20,
        "brier_market": 0.21,
        "logloss_model": 0.60,
        "logloss_market": 0.61,
        "season_fold_scoring_win_rate": 0.65,
        "mean_novig_clv": 0.005,
        "clv_t_stat": 2.0,
        "roi_after_vig": 0.001,
        "calibration_slope": 1.0,
        "calibration_intercept": 0.0,
        "ece": 0.025,
    }
    payload.update(overrides)
    return payload


class TestCFBTruthGate(unittest.TestCase):
    def test_policy_bytes_match_preexisting_frozen_judge_record(self):
        digest = hashlib.sha256(CFB_TRUTH_GATE_POLICY_PATH.read_bytes()).hexdigest()
        self.assertEqual(digest, "9174bafd1e134cc30f3ac4afaf95692de15946617b9e69b545dfd264ab271702")
        self.assertEqual(digest, CFB_TRUTH_GATE_POLICY_SHA256)

    def test_complete_hard_gate_evidence_can_pass_without_mutating_governance(self):
        result = evaluate_cfb_truth_gate(_evidence())
        self.assertTrue(result.passes)
        self.assertEqual(result.status, "PASS")
        output = result.to_dict()
        self.assertFalse(output["governance"]["eligible_changed"])
        self.assertFalse(output["governance"]["model_p_created"])
        self.assertEqual(output["diagnostics"]["target_roi_after_vig"], 0.02)

    def test_two_percent_roi_is_target_not_frozen_hard_minimum(self):
        gate = CFBTruthGate()
        self.assertEqual(gate.gates["min_roi_after_vig"], 0.0)
        self.assertEqual(gate.gates["target_roi_after_vig"], 0.02)
        self.assertTrue(evaluate_cfb_truth_gate(_evidence(roi_after_vig=0.0001)).passes)
        blocked = evaluate_cfb_truth_gate(_evidence(roi_after_vig=0.0))
        self.assertIn("ROI_AFTER_VIG_NOT_POSITIVE", blocked.failures)

    def test_predictive_market_benchmarks_and_fold_rate_are_hard_gates(self):
        cases = {
            "brier_model": (0.21, "BRIER_DOES_NOT_BEAT_MARKET"),
            "logloss_model": (0.61, "LOGLOSS_DOES_NOT_BEAT_MARKET"),
            "season_fold_scoring_win_rate": (0.649, "SEASON_FOLD_SCORING_WIN_RATE_BELOW_FLOOR"),
            "n_forward_seasons": (3, "FORWARD_SEASONS_BELOW_FLOOR"),
            "clv_t_stat": (1.99, "CLV_T_STAT_BELOW_FLOOR"),
        }
        for field, (value, expected) in cases.items():
            with self.subTest(field=field):
                result = evaluate_cfb_truth_gate(_evidence(**{field: value}))
                self.assertFalse(result.passes)
                self.assertIn(expected, result.failures)

    def test_calibration_sample_and_clv_boundaries(self):
        self.assertTrue(evaluate_cfb_truth_gate(_evidence(calibration_slope=0.9)).passes)
        self.assertTrue(evaluate_cfb_truth_gate(_evidence(calibration_slope=1.1)).passes)
        self.assertTrue(evaluate_cfb_truth_gate(_evidence(calibration_intercept=0.03)).passes)
        self.assertTrue(evaluate_cfb_truth_gate(_evidence(mean_novig_clv=0.005)).passes)
        self.assertTrue(evaluate_cfb_truth_gate(_evidence(n_promoted=200)).passes)
        cases = {
            "calibration_slope": (1.101, "CALIBRATION_SLOPE_OUT_OF_RANGE"),
            "calibration_intercept": (0.031, "CALIBRATION_INTERCEPT_OUT_OF_RANGE"),
            "ece": (0.026, "ECE_ABOVE_MAX"),
            "mean_novig_clv": (0.0049, "MEAN_NOVIG_CLV_BELOW_FLOOR"),
            "n_promoted": (199, "PROMOTED_SAMPLE_BELOW_ABSOLUTE_FLOOR"),
        }
        for field, (value, expected) in cases.items():
            with self.subTest(field=field):
                self.assertIn(expected, evaluate_cfb_truth_gate(_evidence(**{field: value})).failures)

    def test_pit_price_and_binding_guards_fail_closed(self):
        cases = {
            "pit_reproducible": "PIT_REPRODUCIBILITY_FAILED",
            "paired_historical_price_evidence_complete": "PAIRED_HISTORICAL_PRICE_EVIDENCE_REQUIRED",
            "recent_two_season_ok": "RECENT_TWO_SEASON_DETERIORATION",
            "model_artifact_bound": "MODEL_ARTIFACT_UNBOUND",
            "source_evidence_bound": "SOURCE_EVIDENCE_UNBOUND",
            "settlement_evidence_complete": "SETTLEMENT_EVIDENCE_INCOMPLETE",
        }
        for field, expected in cases.items():
            with self.subTest(field=field):
                self.assertIn(expected, evaluate_cfb_truth_gate(_evidence(**{field: False})).failures)

    def test_policy_and_artifact_identity_cannot_be_omitted(self):
        with self.assertRaisesRegex(CFBTruthGateError, "POLICY_SHA256_EVIDENCE_MISMATCH"):
            evaluate_cfb_truth_gate(_evidence(evidence_policy_sha256="0" * 64))
        missing = _evidence()
        missing.pop("market_evidence_sha256")
        with self.assertRaisesRegex(CFBTruthGateError, "SHA256_REQUIRED"):
            evaluate_cfb_truth_gate(missing)

    def test_edge_floor_requires_live_guards_and_exact_three_percent(self):
        self.assertTrue(cfb_candidate_meets_edge_floor(model_probability=0.55, no_vig_market_probability=0.52))
        self.assertFalse(cfb_candidate_meets_edge_floor(model_probability=0.5499, no_vig_market_probability=0.52))
        self.assertFalse(cfb_candidate_meets_edge_floor(model_probability=0.60, no_vig_market_probability=0.50, data_fresh=False))
        with self.assertRaises(CFBTruthGateError):
            cfb_candidate_meets_edge_floor(model_probability=1.01, no_vig_market_probability=0.52)


if __name__ == "__main__":
    unittest.main()
