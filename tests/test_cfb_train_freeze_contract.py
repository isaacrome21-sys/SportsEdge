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
        self.assertIn('SELECTED_CANDIDATE_SERVING_CONTRACT_NOT_YET_MERGED', text)


if __name__ == '__main__':
    unittest.main()
