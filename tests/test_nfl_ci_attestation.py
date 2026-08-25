import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from sportsedge.core.validation.nfl_ci_attestation import verify_nfl_pre_ci_bundle
from sportsedge.sports.nfl.m2 import NFL_M2_FEATURE_CONTRACT, PRODUCTION_NFL_M2_MODEL_ID


class NFLCIAttestationTests(unittest.TestCase):
    def _write_bundle(self, root: Path, *, git_sha: str = "1" * 40):
        math = {
            "math_artifact": {
                "source_sha256": "a" * 64,
                "code_git_sha": git_sha,
            }
        }
        history = {
            "source_sha256": "a" * 64,
            "source_manifest_sha256": "a" * 64,
            "code_git_sha": git_sha,
            "model_id": PRODUCTION_NFL_M2_MODEL_ID,
            "feature_contract": NFL_M2_FEATURE_CONTRACT,
        }
        registry = {
            "source_sha256": "a" * 64,
            "source_manifest_sha256": "a" * 64,
            "model_id": PRODUCTION_NFL_M2_MODEL_ID,
            "feature_contract": NFL_M2_FEATURE_CONTRACT,
            "ci_attestation_state": "UNATTESTED_IN_RUNNING_WORKFLOW",
        }
        paths = {}
        for name, payload in (
            ("nfl_simulator_profile.json", math),
            ("nfl_production_validation.json", history),
            ("nfl_promotion_registry.json", registry),
        ):
            path = root / name
            path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            paths[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest = {
            "schema_version": 2,
            "git_sha": git_sha,
            "source_manifest_sha256": "a" * 64,
            "ci_attestation_state": "PRE_CI_WORKFLOW_CANNOT_SELF_ATTEST",
            "artifacts": [{"path": name, "sha256": digest} for name, digest in sorted(paths.items())],
        }
        (root / "nfl_promotion_evidence_manifest.json").write_text(
            json.dumps(manifest, sort_keys=True), encoding="utf-8"
        )

    def test_exact_successful_workflow_head_attests_bundle(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            sha = "1" * 40
            self._write_bundle(root, git_sha=sha)
            result = verify_nfl_pre_ci_bundle(
                root,
                workflow_name="football-nfl-promotion-evidence",
                workflow_conclusion="success",
                workflow_head_sha=sha,
                workflow_run_id=12345,
            )
            self.assertEqual(result["git_sha"], sha)
            self.assertEqual(result["workflow_run_id"], 12345)
            self.assertEqual(result["model_id"], PRODUCTION_NFL_M2_MODEL_ID)

    def test_zero_or_failed_workflow_cannot_attest(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_bundle(root)
            with self.assertRaisesRegex(ValueError, "NFL_CI_WORKFLOW_NOT_SUCCESSFUL"):
                verify_nfl_pre_ci_bundle(
                    root,
                    workflow_name="football-nfl-promotion-evidence",
                    workflow_conclusion="failure",
                    workflow_head_sha="1" * 40,
                    workflow_run_id=12345,
                )

    def test_wrong_workflow_or_head_cannot_attest(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_bundle(root)
            with self.assertRaisesRegex(ValueError, "NFL_CI_WORKFLOW_NAME_MISMATCH"):
                verify_nfl_pre_ci_bundle(
                    root, workflow_name="some-other-workflow", workflow_conclusion="success",
                    workflow_head_sha="1" * 40, workflow_run_id=12345,
                )
            with self.assertRaisesRegex(ValueError, "NFL_CI_HEAD_SHA_MISMATCH"):
                verify_nfl_pre_ci_bundle(
                    root, workflow_name="football-nfl-promotion-evidence", workflow_conclusion="success",
                    workflow_head_sha="2" * 40, workflow_run_id=12345,
                )

    def test_tampered_artifact_fails_hash_verification(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_bundle(root)
            (root / "nfl_production_validation.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "NFL_CI_ARTIFACT_HASH_MISMATCH"):
                verify_nfl_pre_ci_bundle(
                    root, workflow_name="football-nfl-promotion-evidence", workflow_conclusion="success",
                    workflow_head_sha="1" * 40, workflow_run_id=12345,
                )

    def test_artifact_code_sha_must_match_workflow_head(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_bundle(root, git_sha="1" * 40)
            history_path = root / "nfl_production_validation.json"
            history = json.loads(history_path.read_text())
            history["code_git_sha"] = "2" * 40
            history_path.write_text(json.dumps(history, sort_keys=True), encoding="utf-8")
            manifest_path = root / "nfl_promotion_evidence_manifest.json"
            manifest = json.loads(manifest_path.read_text())
            for row in manifest["artifacts"]:
                if row["path"] == history_path.name:
                    row["sha256"] = hashlib.sha256(history_path.read_bytes()).hexdigest()
            manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "NFL_CI_EVIDENCE_CODE_SHA_MISMATCH"):
                verify_nfl_pre_ci_bundle(
                    root, workflow_name="football-nfl-promotion-evidence", workflow_conclusion="success",
                    workflow_head_sha="1" * 40, workflow_run_id=12345,
                )


if __name__ == "__main__":
    unittest.main()
