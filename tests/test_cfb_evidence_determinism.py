from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from sportsedge.core.validation.evidence_determinism import compare_evidence_directories


_GIT_SHA = "1" * 40
_BUNDLE_SHA = "b" * 64


class CFBEvidenceDeterminismTests(unittest.TestCase):
    def _write_bytes(self, root: Path, name: str, payload: bytes) -> None:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    def _compare(self, baseline: Path, candidate: Path):
        return compare_evidence_directories(
            sport="cfb",
            baseline_dir=baseline,
            candidate_dir=candidate,
            artifacts=["provenance.json", "model.json"],
            identity_artifact="provenance.json",
            expected_git_sha=_GIT_SHA,
            determinism_class="SAME_ENV_SAME_SHA",
            replay_scope="TRAINING_BUNDLE_TO_ARTIFACT",
            clock_perturbation="BASELINE_TZ=UTC;REPLAY_TZ=Pacific/Kiritimati",
            source_identity_field="training_bundle_sha256",
            baseline_label="CI_ATTEMPT_001",
            candidate_label="CI_REPLAY_001",
        )

    def test_training_bundle_sha_is_the_frozen_input_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "baseline"
            candidate = root / "candidate"
            provenance = {
                "sport": "cfb",
                "code_git_sha": _GIT_SHA,
                "training_bundle_sha256": _BUNDLE_SHA,
                "determinism_class": "SAME_ENV_SAME_SHA",
                "replay_scope": "TRAINING_BUNDLE_TO_ARTIFACT",
            }
            provenance_bytes = (json.dumps(provenance, indent=2, sort_keys=True) + "\n").encode("utf-8")
            model_bytes = (json.dumps({"weights": [0.1, -0.2]}, indent=2, sort_keys=True) + "\n").encode("utf-8")
            for directory in (baseline, candidate):
                self._write_bytes(directory, "provenance.json", provenance_bytes)
                self._write_bytes(directory, "model.json", model_bytes)

            report = self._compare(baseline, candidate)

            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["gate_basis"], "BYTE_IDENTITY")
            self.assertEqual(report["source_identity_field"], "training_bundle_sha256")
            self.assertEqual(report["source_identity_sha256"], _BUNDLE_SHA)
            self.assertIsNone(report["source_manifest_sha256"])
            self.assertEqual(report["determinism_class"], "SAME_ENV_SAME_SHA")
            self.assertEqual(report["replay_scope"], "TRAINING_BUNDLE_TO_ARTIFACT")
            self.assertTrue(report["all_bytes_equal"])

    def test_training_bundle_identity_mismatch_blocks_before_output_comparison(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "baseline"
            candidate = root / "candidate"
            baseline_provenance = {
                "sport": "cfb",
                "code_git_sha": _GIT_SHA,
                "training_bundle_sha256": "a" * 64,
            }
            candidate_provenance = {
                "sport": "cfb",
                "code_git_sha": _GIT_SHA,
                "training_bundle_sha256": "c" * 64,
            }
            self._write_bytes(
                baseline,
                "provenance.json",
                (json.dumps(baseline_provenance, sort_keys=True) + "\n").encode("utf-8"),
            )
            self._write_bytes(
                candidate,
                "provenance.json",
                (json.dumps(candidate_provenance, sort_keys=True) + "\n").encode("utf-8"),
            )
            self._write_bytes(baseline, "model.json", b'{"weights":[1.0]}\n')
            self._write_bytes(candidate, "model.json", b'{"weights":[9.0]}\n')

            report = self._compare(baseline, candidate)

            self.assertEqual(report["status"], "BLOCKED")
            self.assertEqual(report["failure_class"], "SOURCE_IDENTITY_MISMATCH")
            self.assertEqual(
                report["reason"],
                "SOURCE_IDENTITY_SHA256_MISMATCH:training_bundle_sha256",
            )


if __name__ == "__main__":
    unittest.main()
