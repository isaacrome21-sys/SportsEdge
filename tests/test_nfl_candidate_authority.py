import json
from pathlib import Path
import unittest

from sportsedge.sports.nfl.candidate_authority import (
    NFLCandidateAuthorityError,
    candidate_authority,
    require_reserved_2026_use,
    require_run_it_model_authority,
)


class NFLCandidateAuthorityTests(unittest.TestCase):
    def test_rejected_frozen_attempt_is_paper_only_zero_units(self):
        d = candidate_authority({
            "status": "REJECTED_FROZEN_ATTEMPT",
            "promotion_authority": False,
            "model_p_authority": False,
            "frozen_artifact_binding": True,
            "truth_gate_authorized": False,
        })
        self.assertFalse(d.run_it_model_authorized)
        self.assertTrue(d.paper_only)
        self.assertEqual(d.stake_units, 0.0)
        self.assertFalse(d.model_p_authority)
        self.assertFalse(d.staking_authority)
        with self.assertRaisesRegex(NFLCandidateAuthorityError, "NFL_CANDIDATE_NOT_AUTHORIZED"):
            require_run_it_model_authority({"status": "REJECTED_FROZEN_ATTEMPT"})

    def test_untested_candidate_cannot_drive_run_it(self):
        d = candidate_authority({"status": "UNTESTED"})
        self.assertFalse(d.run_it_model_authorized)
        self.assertEqual(d.stake_units, 0.0)
        self.assertFalse(d.staking_authority)

    def test_promoted_label_alone_is_not_enough(self):
        d = candidate_authority({"status": "PROMOTED"})
        self.assertFalse(d.run_it_model_authorized)
        self.assertIn("AUTHORITY_INCOMPLETE", d.reason)

    def test_full_model_authority_never_manufactures_stake_size(self):
        d = require_run_it_model_authority({
            "status": "PROMOTED",
            "promotion_authority": True,
            "model_p_authority": True,
            "frozen_artifact_binding": True,
            "truth_gate_authorized": True,
        })
        self.assertTrue(d.run_it_model_authorized)
        self.assertFalse(d.paper_only)
        self.assertIsNone(d.stake_units)
        self.assertFalse(d.staking_authority)
        self.assertIn("STAKING_SEPARATE", d.reason)

    def test_2026_reserved_stream_blocks_tuning_and_card_feedback(self):
        blocked = [
            "TUNE_CANDIDATE",
            "SELECT_ARCHITECTURE",
            "CHANGE_FEATURE_POLICY",
            "CHANGE_THRESHOLDS",
            "RUN_IT_BET_FEEDBACK",
        ]
        for purpose in blocked:
            with self.subTest(purpose=purpose):
                with self.assertRaisesRegex(NFLCandidateAuthorityError, "NFL_2026_RESERVED_STREAM_USE_BLOCKED"):
                    require_reserved_2026_use(purpose)
        self.assertEqual(
            require_reserved_2026_use("FIRST_WRITE_PREDICTION_CAPTURE"),
            "FIRST_WRITE_PREDICTION_CAPTURE",
        )

    def test_current_run_it_surface_declares_context_only_without_authorized_model(self):
        cfg = json.loads(Path("config/run_it_surface.json").read_text())
        nfl = cfg["sports"]["NFL"]
        self.assertEqual(nfl["bettor_facing_model_authority"], "NONE_PENDING_PROMOTION")
        self.assertEqual(nfl["fallback_without_authorized_model"], "MARKET_CONTEXT_ONLY")
        self.assertEqual(nfl["research_candidate_usage"], "PAPER_ONLY_ZERO_UNITS")
        self.assertEqual(nfl["reserved_2026_stream_usage"], "FORWARD_EVIDENCE_ONLY_NO_TUNING")

    def test_candidate_policy_is_not_silently_frozen_by_code_pr(self):
        policy = json.loads(Path("config/nfl_candidate_authority_policy_v1.json").read_text())
        self.assertEqual(policy["policy_status"], "DRAFT_PRE_EVIDENCE_HUMAN_REVIEW_REQUIRED")
        self.assertFalse(policy["authorized_model_behavior"]["may_size_stake"])
        self.assertIsNone(policy["authorized_model_behavior"]["stake_units"])


if __name__ == "__main__":
    unittest.main()
