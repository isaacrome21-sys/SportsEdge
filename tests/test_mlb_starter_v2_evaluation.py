from __future__ import annotations

import unittest

from sportsedge.mlb_starter_v2_evaluation import (
    EVALUATION_CONFIG,
    EVALUATION_CONFIG_SHA256,
    EVALUATION_LINES,
    SIMULATIONS_PER_GAME_MODEL,
    promotion_gate,
)
from sportsedge.source_lineage import canonical_json_sha256


def _summary(pred: float, brier: float) -> dict:
    return {
        "by_event": {
            f"GAME_TOTAL_OVER_{line:g}": {
                "n": 100,
                "mean_predicted_p": pred,
                "observed_rate": 0.50,
                "brier": brier,
            }
            for line in EVALUATION_LINES
        }
    }


class StarterV2EvaluationTests(unittest.TestCase):
    def test_contract_frozen(self):
        self.assertEqual(EVALUATION_LINES, (6.5, 7.5, 8.5, 9.5))
        self.assertEqual(SIMULATIONS_PER_GAME_MODEL, 20_000)
        self.assertEqual(EVALUATION_CONFIG_SHA256, canonical_json_sha256(EVALUATION_CONFIG))
        self.assertEqual(EVALUATION_CONFIG["coverage_start"], "2026-08-01")
        self.assertEqual(EVALUATION_CONFIG["coverage_end"], "2026-08-31")

    def test_pass_requires_both_improvements(self):
        result = promotion_gate(baseline=_summary(0.60, 0.25), candidate=_summary(0.55, 0.24))
        self.assertTrue(result["mean_abs_calibration_gap"]["pass"])
        self.assertTrue(result["mean_brier"]["pass"])
        self.assertTrue(result["gate_pass"])
        self.assertEqual(result["decision"], "PASS_PROVISIONAL")

    def test_one_failed_leg_fails_gate(self):
        result = promotion_gate(baseline=_summary(0.60, 0.25), candidate=_summary(0.55, 0.26))
        self.assertTrue(result["mean_abs_calibration_gap"]["pass"])
        self.assertFalse(result["mean_brier"]["pass"])
        self.assertFalse(result["gate_pass"])
        self.assertEqual(result["decision"], "FAIL_KEEP_DEFENSE_BLEND")

    def test_equal_is_not_improvement(self):
        result = promotion_gate(baseline=_summary(0.60, 0.25), candidate=_summary(0.60, 0.25))
        self.assertFalse(result["gate_pass"])


if __name__ == "__main__":
    unittest.main()
