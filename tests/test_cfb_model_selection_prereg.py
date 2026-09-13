import json
import unittest
from pathlib import Path

from sportsedge.sports.cfb.model_selection_prereg import audit_model_selection_prereg


ROOT = Path(__file__).resolve().parents[1]


class TestCFBModelSelectionPrereg(unittest.TestCase):
    def policy(self):
        return json.loads((ROOT / "config/cfb_model_selection_policy_v1.json").read_text())

    def complete_candidate(self, family):
        return {
            "family": family,
            "status": "PREREGISTERED_UNEVALUATED",
            "formula": "frozen formula text",
            "feature_list": ["feature_a"],
            "weighting_blending_constants": {},
            "training_window": {"start_season": 2015, "end_season": 2025},
            "hyperparameter_policy": {"mode": "FROZEN"},
            "source_contract_identity": "SOURCE_CONTRACT_V1",
            "code_sha256": "a" * 64,
            "config_sha256": "b" * 64,
        }

    def test_current_policy_without_candidate_specs_is_blocked_without_spending_attempt(self):
        out = audit_model_selection_prereg(self.policy(), None)
        self.assertEqual(out["status"], "BLOCKED_PREREG_INCOMPLETE")
        self.assertEqual(out["attempts_consumed"], 0)
        self.assertFalse(out["attempt_consumed_by_this_audit"])
        self.assertFalse(out["model_fit_performed"])
        self.assertFalse(out["model_p_created"])
        self.assertFalse(out["promotion_authority"])
        self.assertIn("CANDIDATE_PREREGISTRATION_MISSING", out["blockers"])
        self.assertEqual(len(out["candidate_results"]), 4)

    def test_all_four_complete_preregistered_candidates_make_first_evaluation_ready(self):
        policy = self.policy()
        prereg = {"candidates": {family: self.complete_candidate(family) for family in policy["candidate_families_predeclared"]}}
        out = audit_model_selection_prereg(policy, prereg)
        self.assertEqual(out["status"], "READY_FOR_FIRST_EVALUATION")
        self.assertEqual(out["blockers"], [])
        self.assertTrue(all(row["complete"] for row in out["candidate_results"]))
        self.assertFalse(out["attempt_consumed_by_this_audit"])

    def test_missing_hash_blocks_candidate(self):
        policy = self.policy()
        candidates = {family: self.complete_candidate(family) for family in policy["candidate_families_predeclared"]}
        candidates[policy["candidate_families_predeclared"][0]]["code_sha256"] = None
        out = audit_model_selection_prereg(policy, {"candidates": candidates})
        self.assertEqual(out["status"], "BLOCKED_PREREG_INCOMPLETE")
        first = out["candidate_results"][0]
        self.assertIn("CODE_SHA256_MISSING_OR_INVALID", first["blockers"])

    def test_post_evaluation_fields_are_forbidden_in_preregistration(self):
        policy = self.policy()
        candidates = {family: self.complete_candidate(family) for family in policy["candidate_families_predeclared"]}
        candidates[policy["candidate_families_predeclared"][0]]["rmse"] = 1.0
        out = audit_model_selection_prereg(policy, {"candidates": candidates})
        self.assertEqual(out["status"], "BLOCKED_PREREG_INCOMPLETE")
        self.assertIn("POST_EVALUATION_FIELD_PRESENT_IN_PREREGISTRATION", out["candidate_results"][0]["blockers"])

    def test_nonzero_attempt_count_cannot_represent_first_evaluation_readiness(self):
        policy = self.policy()
        policy["attempts_consumed"] = 1
        prereg = {"candidates": {family: self.complete_candidate(family) for family in policy["candidate_families_predeclared"]}}
        out = audit_model_selection_prereg(policy, prereg)
        self.assertEqual(out["status"], "BLOCKED_PREREG_INCOMPLETE")
        self.assertIn("FIRST_EVALUATION_GATE_REQUIRES_ZERO_ATTEMPTS_CONSUMED", out["blockers"])


if __name__ == "__main__":
    unittest.main()
