import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_nfl_v2g_prospective.py"
spec = importlib.util.spec_from_file_location("evaluate_nfl_v2g_prospective", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class NFLV2GProspectiveEvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.settlements = self.root / "settlements"
        self.settlements.mkdir()
        self.policy = self.root / "policy.json"
        self.policy.write_text(json.dumps({
            "schema_version": mod.POLICY_SCHEMA,
            "candidate_id": "nfl_m2_scoring_event_v2g_candidate",
            "prospective_metrics": {
                "clv_probability_threshold": 0.005,
                "after_vig_roi_threshold": 0.02,
                "calibration_slope_min": 0.90,
                "calibration_slope_max": 1.10,
                "calibration_intercept_abs_max": 0.03,
                "ece_max": 0.025
            },
            "checkpoints": {
                "fixed_settled_market_counts": [50, 100, 150, 200],
                "minimum_promotion_count": 200
            }
        }), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def write_row(self, idx, model_p=0.60, market_p=0.55, outcome=None, predictive_status="SCORED"):
        y = idx % 2 if outcome is None else outcome
        def ll(p):
            import math
            return -math.log(p if y else 1 - p)
        def brier(p):
            return (p - y) ** 2
        if predictive_status == "SCORED":
            pred = {
                "status": "SCORED",
                "model_probability": model_p,
                "closing_no_vig_probability": market_p,
                "outcome": y,
                "model_log_loss": ll(model_p),
                "closing_market_log_loss": ll(market_p),
                "model_brier": brier(model_p),
                "closing_market_brier": brier(market_p)
            }
        else:
            pred = {"status": predictive_status}
        paper = {
            "status": "SETTLED_PAPER_CANDIDATE",
            "after_vig_profit_units": 0.1,
            "clv": {"line_clv": 0.5, "probability_clv": 0.01 if predictive_status == "SCORED" else None}
        }
        payload = {
            "schema_version": mod.SETTLEMENT_SCHEMA,
            "status": "SETTLED_PROSPECTIVE_EVIDENCE" if predictive_status == "SCORED" else "SETTLED_INCONCLUSIVE_MISSING_CAPTURE",
            "game_id": f"g{idx:03d}",
            "kickoff_utc": f"2026-10-{1 + idx // 24:02d}T{idx % 24:02d}:00:00+00:00",
            "predictive_evaluation": {"spread": dict(pred), "total": dict(pred)},
            "paper_evaluation": {"spread": dict(paper), "total": dict(paper)}
        }
        (self.settlements / f"g{idx:03d}.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_no_gate_evaluation_before_first_fixed_checkpoint(self):
        for i in range(49):
            self.write_row(i)
        result = mod.evaluate(self.settlements, self.policy)
        self.assertEqual("PRECHECKPOINT_NO_GATE_EVALUATION", result["status"])
        self.assertIsNone(result["checkpoint_evaluated"])
        self.assertEqual(50, result["next_checkpoint"])

    def test_checkpoint_uses_exact_first_n_and_ignores_between_checkpoint_peeking(self):
        for i in range(50):
            self.write_row(i)
        at_50 = mod.evaluate(self.settlements, self.policy)
        self.assertEqual(50, at_50["checkpoint_evaluated"])
        self.assertEqual("FIXED_CHECKPOINT_DIAGNOSTIC_ONLY", at_50["status"])
        sample_ids = at_50["markets"]["spread"]["sample_game_ids"]
        self.assertEqual(50, len(sample_ids))

        self.write_row(50, model_p=0.01, market_p=0.99, outcome=1)
        at_51 = mod.evaluate(self.settlements, self.policy)
        self.assertEqual(50, at_51["checkpoint_evaluated"])
        self.assertEqual(sample_ids, at_51["markets"]["spread"]["sample_game_ids"])
        self.assertEqual(100, at_51["next_checkpoint"])
        self.assertFalse(at_51["promotion_authority"])
        self.assertFalse(at_51["official_status_granted"])

    def test_missing_close_is_not_dropped_or_replaced(self):
        for i in range(49):
            self.write_row(i)
        self.write_row(49, predictive_status="INCONCLUSIVE_MISSING_CAPTURE")
        self.write_row(50)
        result = mod.evaluate(self.settlements, self.policy)
        spread = result["markets"]["spread"]
        self.assertEqual(50, result["checkpoint_evaluated"])
        self.assertEqual(50, spread["n"])
        self.assertEqual(49, spread["predictive_scorable_n"])
        self.assertEqual(1, spread["missing_close_n"])
        self.assertFalse(spread["complete_close_evidence"])
        self.assertEqual("g049", spread["sample_game_ids"][-1])
        self.assertEqual("FAIL", result["gates"]["spread"]["complete_close_evidence"])
        self.assertEqual(50, spread["paper_candidate_n"])


if __name__ == "__main__":
    unittest.main()
