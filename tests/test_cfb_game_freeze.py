from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from sportsedge.sports.cfb.game_freeze import (
    CFBGameFreezeError,
    load_cfb_game_freeze,
    verify_frozen_cfb_game_artifact,
)

ROOT = Path(__file__).resolve().parents[1]


class CFBGameFreezeTests(unittest.TestCase):
    def test_committed_registry_is_explicitly_unfrozen(self):
        payload = json.loads((ROOT / "config/cfb_game_model_freeze.json").read_text())
        self.assertEqual(payload["status"], "UNFROZEN")
        self.assertEqual(payload["blocker"], "CFB_PIT_TRAINING_BUNDLE_UNAVAILABLE")
        self.assertFalse(payload["promotion_authority"])
        self.assertFalse(payload["evidence_clock_authority"])
        self.assertIsNone(payload["artifact_sha256"])
        self.assertIsNone(payload["artifact_file_sha256"])

    def test_unfrozen_registry_fails_closed(self):
        with self.assertRaisesRegex(CFBGameFreezeError, "CFB_PIT_TRAINING_BUNDLE_UNAVAILABLE"):
            load_cfb_game_freeze(ROOT / "config/cfb_game_model_freeze.json")

    def test_frozen_registry_requires_all_identity_hashes(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "freeze.json"
            path.write_text(json.dumps({
                "schema_version": 1,
                "sport": "CFB",
                "status": "FROZEN",
                "artifact_path": "models/cfb_joint_v1.json",
                "artifact_sha256": "a" * 64,
                "artifact_file_sha256": "b" * 64,
                "model_code_sha256": "c" * 64,
                "training_source_sha256": "d" * 64,
                "source_manifest_sha256": "e" * 64,
                "predictive_code_manifest_sha256": "f" * 64,
                "acquisition_code_manifest_sha256": "1" * 64,
                "fit_max_season": 2025,
                "promotion_authority": False,
                "evidence_clock_authority": False,
            }))
            row = load_cfb_game_freeze(path)
            self.assertEqual(row["fit_max_season"], 2025)

    def test_exact_file_and_internal_artifact_identity_are_separate(self):
        payload = {
            "artifact_sha256": "a" * 64,
            "model_code_sha256": "c" * 64,
            "training_source_sha256": "d" * 64,
        }
        raw = (json.dumps(payload, sort_keys=True) + "\n").encode()
        registry = {
            "artifact_sha256": "a" * 64,
            "artifact_file_sha256": sha256(raw).hexdigest(),
            "model_code_sha256": "c" * 64,
            "training_source_sha256": "d" * 64,
        }
        verify_frozen_cfb_game_artifact(payload, artifact_bytes=raw, registry=registry)
        registry["artifact_file_sha256"] = "0" * 64
        with self.assertRaisesRegex(CFBGameFreezeError, "ARTIFACT_FILE_SHA_MISMATCH"):
            verify_frozen_cfb_game_artifact(payload, artifact_bytes=raw, registry=registry)

    def test_current_release_capture_cannot_be_claimed_as_pit(self):
        workflow = (ROOT / ".github/workflows/cfb-current-history-capture.yml").read_text()
        self.assertIn("CURRENT_HISTORICAL_RELEASE_NOT_POINT_IN_TIME", workflow)
        self.assertIn("point_in_time_as_of_game_proven': False", workflow)
        self.assertIn("promotion_evidence': False", workflow)

    def test_runtime_has_no_training_source_environment_bypass(self):
        source = (ROOT / "scripts/run_cfb_auto.py").read_text()
        self.assertNotIn("SPORTSEDGE_CFB_TRAINING_SOURCE_SHA256", source)
        self.assertIn("load_cfb_game_freeze", source)
        self.assertIn("expected_training_source_sha256=registry[\"training_source_sha256\"]", source)


if __name__ == "__main__":
    unittest.main()
