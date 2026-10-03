from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CFBTrainFreezeContractTests(unittest.TestCase):
    def test_frozen_attempt_budget_is_unspent(self):
        policy = json.loads((ROOT / 'config/cfb_model_selection_policy_v1.json').read_text())
        prereg = json.loads((ROOT / 'config/cfb_model_candidate_prereg_v1.json').read_text())
        self.assertEqual(policy['status'], 'FROZEN_BEFORE_CANDIDATE_EVALUATION')
        self.assertEqual(policy['candidate_attempt_budget'], 4)
        self.assertEqual(policy['attempts_consumed'], 0)
        self.assertEqual(prereg['governance']['attempts_consumed'], 0)
        self.assertFalse(prereg['governance']['evaluation_performed'])

    def test_game_freeze_remains_fail_closed_before_genuine_fit(self):
        freeze = json.loads((ROOT / 'config/cfb_game_model_freeze.json').read_text())
        self.assertEqual(freeze['status'], 'UNFROZEN')
        self.assertIsNone(freeze['artifact_sha256'])
        self.assertFalse(freeze['promotion_authority'])
        self.assertFalse(freeze['evidence_clock_authority'])

    def test_train_freeze_workflow_never_pushes_main(self):
        text = (ROOT / '.github/workflows/cfb-train-freeze.yml').read_text()
        self.assertNotIn('git push origin main', text)
        self.assertNotIn('git push origin HEAD:main', text)
        self.assertIn('secrets.CFBD_API_KEY', text)
        self.assertIn('PREFLIGHT_ONLY', text)
        self.assertIn('CONSUME_ALL_FOUR_CFB_ATTEMPTS', text)
        self.assertIn('CFB_TRAIN_FREEZE_PREFLIGHT_ONLY', text)
        self.assertIn('CFB_TRAIN_FREEZE_EVALUATION_CONFIRMATION_ACCEPTED', text)
        self.assertIn('activate_cfb_selected_candidate_freeze.py', text)

    def test_evaluation_workflow_persists_public_winner_and_model_proposal_evidence(self):
        text = (ROOT / '.github/workflows/cfb-reconstructed-selection-materialize.yml').read_text()
        self.assertIn('candidate_bakeoff_result.json', text)
        self.assertIn('cfb_selected_candidate_model_proposal.json', text)
        self.assertIn('cfb_selected_candidate_model_build_attestation.json', text)
        self.assertNotIn('cp "$RUNNER_TEMP/cfb_reconstructed_selection_rows.json"', text)
        self.assertNotIn('cp "$RUNNER_TEMP/cfb_candidate_bakeoff_private_capture.json"', text)


if __name__ == '__main__':
    unittest.main()
