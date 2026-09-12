import copy
import json
import unittest
from pathlib import Path

from sportsedge.sports.nfl.m2_v2f_candidate import NFL_M2_V2F_CANDIDATE_MODEL_ID
from sportsedge.sports.nfl.m2_v2f_forward import audit_forward_rows, validate_forward_row, NFLV2FForwardEvidenceError

POLICY = json.loads(Path("config/research/nfl_v2f_forward_validation_policy_2026-09-12.json").read_text())


def row():
    return {
        "candidate_id": NFL_M2_V2F_CANDIDATE_MODEL_ID,
        "preregistration_commit_sha": "5385eaa7d7f78d6fcf945df913ce8deb74c8e4a7",
        "candidate_code_git_sha": "f" * 40,
        "event_id": "2026_02_X_Y",
        "market": "SPREAD",
        "selection": "HOME",
        "threshold": -3.0,
        "book": "DK",
        "event_start_utc": "2026-09-20T17:00:00+00:00",
        "prediction_captured_at_utc": "2026-09-20T15:30:00+00:00",
        "decision_quote_captured_at_utc": "2026-09-20T15:35:00+00:00",
        "close_quote_captured_at_utc": "2026-09-20T16:50:00+00:00",
        "final_outcome_observed_at_utc": "2026-09-20T20:30:00+00:00",
        "model_probability": 0.57,
        "prediction_provenance": "frozen_model_artifact",
        "prediction_sha256": "1" * 64,
        "decision_quote_provenance": "provider_snapshot",
        "decision_quote_sha256": "2" * 64,
        "close_quote_provenance": "provider_snapshot",
        "close_quote_sha256": "3" * 64,
        "final_result_provenance": "official_final_score",
        "final_result_sha256": "4" * 64,
    }


class NFLV2FForwardEvidenceTests(unittest.TestCase):
    def test_valid_row_is_prospective_but_has_no_promotion_authority(self):
        out = audit_forward_rows([row()], POLICY)
        self.assertEqual(out["status"], "PROSPECTIVE_EVIDENCE_VALID")
        self.assertEqual(out["valid_observation_count"], 1)
        self.assertEqual(out["highest_checkpoint_reached"], 0)
        self.assertFalse(out["promotion_authority"])
        self.assertFalse(out["may_change_market_eligibility"])

    def test_pre_freeze_event_is_rejected(self):
        bad = row()
        bad["event_start_utc"] = "2026-09-12T03:00:00+00:00"
        bad["prediction_captured_at_utc"] = "2026-09-12T02:00:00+00:00"
        with self.assertRaisesRegex(NFLV2FForwardEvidenceError, "EVENT_NOT_PROSPECTIVE"):
            validate_forward_row(bad, POLICY)

    def test_reconstructed_prediction_is_rejected(self):
        bad = row()
        bad["prediction_provenance"] = "reconstructed"
        out = audit_forward_rows([bad], POLICY)
        self.assertEqual(out["status"], "BLOCKED_PROSPECTIVE_EVIDENCE")
        self.assertIn("PROVENANCE_FORBIDDEN:prediction", out["failures"][0]["reason"])

    def test_close_must_be_after_decision_and_before_start(self):
        bad = row()
        bad["close_quote_captured_at_utc"] = bad["decision_quote_captured_at_utc"]
        with self.assertRaisesRegex(NFLV2FForwardEvidenceError, "MARKET_TIME_INVALID"):
            validate_forward_row(bad, POLICY)

    def test_policy_candidate_identity_must_match_code(self):
        bad_policy = copy.deepcopy(POLICY)
        bad_policy["candidate_id"] = "wrong"
        out = audit_forward_rows([row()], bad_policy)
        self.assertEqual(out["status"], "BLOCKED_PROSPECTIVE_EVIDENCE") if "status" in out else None

    def test_duplicate_same_market_observation_blocks_audit(self):
        out = audit_forward_rows([row(), row()], POLICY)
        self.assertEqual(out["status"], "BLOCKED_PROSPECTIVE_EVIDENCE")
        self.assertEqual(out["valid_observation_count"], 1)
        self.assertEqual(out["invalid_observation_count"], 1)


if __name__ == "__main__":
    unittest.main()
