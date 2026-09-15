from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from sportsedge.sports.cfb.participation_model import (
    CFBParticipationModelError,
    load_cfb_participation_policy,
    require_frozen_cfb_participation_model,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config/cfb_prop_participation_model_v1.json"


class CFBParticipationModelTests(unittest.TestCase):
    def test_checked_in_policy_is_explicitly_unfitted_and_non_authoritative(self):
        payload = load_cfb_participation_policy(POLICY)
        self.assertEqual(payload["status"], "UNFITTED_RESEARCH_ONLY")
        self.assertEqual(payload["engine_validation_status"], "NOT_RUN")
        self.assertFalse(payload["market_data_used_as_feature"])
        self.assertFalse(payload["promotion_authority"])
        self.assertFalse(payload["activation_authority"])
        self.assertIn("STARTING_QB_HARD_WIRED", payload["structural_blockers"])
        self.assertIn("CFB_BLOWOUT_SUBSTITUTION_UNMODELED", payload["structural_blockers"])
        with self.assertRaisesRegex(CFBParticipationModelError, "CFB_PROP_PARTICIPATION_MODEL_NOT_FROZEN"):
            require_frozen_cfb_participation_model(POLICY)

    def test_market_data_can_never_become_participation_input(self):
        payload = json.loads(POLICY.read_text(encoding="utf-8"))
        payload["market_data_used_as_feature"] = True
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "policy.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(CFBParticipationModelError, "CFB_PROP_PARTICIPATION_MARKET_FEATURE_FORBIDDEN"):
                load_cfb_participation_policy(path)

    def test_frozen_state_requires_independent_forward_validation(self):
        payload = json.loads(POLICY.read_text(encoding="utf-8"))
        payload.update({
            "status": "FROZEN",
            "engine_validation_status": "NOT_RUN",
            "artifact_path": "artifacts/football/cfb_participation_model_v1.json",
            "artifact_sha256": "a" * 64,
            "fit_code_git_sha": "b" * 40,
            "training_source_manifest_sha256": "c" * 64,
        })
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "policy.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(CFBParticipationModelError, "CFB_PROP_PARTICIPATION_MODEL_NOT_FORWARD_VALIDATED"):
                require_frozen_cfb_participation_model(path)

    def test_valid_frozen_state_is_hash_bound_but_still_non_promotional(self):
        payload = json.loads(POLICY.read_text(encoding="utf-8"))
        payload.update({
            "status": "FROZEN",
            "engine_validation_status": "PASSED",
            "artifact_path": "artifacts/football/cfb_participation_model_v1.json",
            "artifact_sha256": "a" * 64,
            "fit_code_git_sha": "b" * 40,
            "training_source_manifest_sha256": "c" * 64,
        })
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "policy.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            checked = require_frozen_cfb_participation_model(path)
            self.assertEqual(checked["artifact_sha256"], "a" * 64)
            self.assertEqual(checked["fit_code_git_sha"], "b" * 40)
            self.assertEqual(checked["training_source_manifest_sha256"], "c" * 64)
            self.assertFalse(checked["promotion_authority"])
            self.assertFalse(checked["activation_authority"])


if __name__ == "__main__":
    unittest.main()
