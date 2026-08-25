import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from sportsedge.core.validation.nfl_ci_attestation import verify_nfl_pre_ci_bundle
from sportsedge.sports.nfl.m2 import NFLM2ScoreModel, NFL_M2_FEATURE_CONTRACT, PRODUCTION_NFL_M2_MODEL_ID
from sportsedge.sports.nfl.model_artifact import build_nfl_m2_model_artifact


class NFLCIAttestationTests(unittest.TestCase):
    def _model_artifact(self, git_sha: str):
        model = NFLM2ScoreModel(
            model_id=PRODUCTION_NFL_M2_MODEL_ID, feature_contract=NFL_M2_FEATURE_CONTRACT,
            feature_names=("home_x", "away_x"), feature_means=(0.0, 0.0), feature_scales=(1.0, 1.0),
            margin_coefficients=(0.0, 1.0, -1.0), total_coefficients=(44.0, 0.1, 0.1),
            train_seasons=(2024, 2025), ridge_alpha=10.0, margin_sigma=13.0, total_sigma=10.0,
            residual_correlation=0.0, residual_pairs=((1.0, 1.0), (-1.0, -1.0)),
        )
        return build_nfl_m2_model_artifact(model, code_git_sha=git_sha, source_manifest_sha256="a" * 64)

    def _write_bundle(self, root: Path, *, git_sha: str = "1" * 40):
        math = {"math_artifact": {"source_sha256": "a" * 64, "code_git_sha": git_sha}}
        history = {"source_sha256": "a" * 64, "source_manifest_sha256": "a" * 64,
                   "code_git_sha": git_sha, "model_id": PRODUCTION_NFL_M2_MODEL_ID,
                   "feature_contract": NFL_M2_FEATURE_CONTRACT}
        registry = {"source_sha256": "a" * 64, "source_manifest_sha256": "a" * 64,
                    "model_id": PRODUCTION_NFL_M2_MODEL_ID, "feature_contract": NFL_M2_FEATURE_CONTRACT,
                    "ci_attestation_state": "UNATTESTED_IN_RUNNING_WORKFLOW"}
        source = {"manifest_sha256": "a" * 64}
        payloads = {
            "nfl_simulator_profile.json": math,
            "nfl_production_validation.json": history,
            "nfl_promotion_registry.json": registry,
            "nfl_source_manifest.json": source,
            "nfl_m2_model.json": self._model_artifact(git_sha),
        }
        hashes = {}
        for name, payload in payloads.items():
            path = root / name; path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest = {"schema_version": 2, "git_sha": git_sha, "source_manifest_sha256": "a" * 64,
                    "ci_attestation_state": "PRE_CI_WORKFLOW_CANNOT_SELF_ATTEST",
                    "artifacts": [{"path": n, "sha256": h} for n, h in sorted(hashes.items())]}
        (root / "nfl_promotion_evidence_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def _verify(self, root: Path, *, sha="1" * 40, conclusion="success", name="football-nfl-promotion-evidence"):
        return verify_nfl_pre_ci_bundle(root, workflow_name=name, workflow_conclusion=conclusion,
                                        workflow_head_sha=sha, workflow_run_id=12345)

    def test_exact_successful_head_attests_model_and_bundle(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp); self._write_bundle(root)
            result = self._verify(root)
            self.assertEqual(result["git_sha"], "1" * 40)
            self.assertEqual(result["trained_through_season"], 2025)
            self.assertEqual(result["verified_artifact_count"], 5)
            self.assertRegex(result["model_artifact_sha256"], r"^[0-9a-f]{64}$")

    def test_failed_or_wrong_workflow_cannot_attest(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp); self._write_bundle(root)
            with self.assertRaisesRegex(ValueError, "NFL_CI_WORKFLOW_NOT_SUCCESSFUL"):
                self._verify(root, conclusion="failure")
            with self.assertRaisesRegex(ValueError, "NFL_CI_WORKFLOW_NAME_MISMATCH"):
                self._verify(root, name="other")

    def test_wrong_head_cannot_attest(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp); self._write_bundle(root)
            with self.assertRaisesRegex(ValueError, "NFL_CI_HEAD_SHA_MISMATCH"):
                self._verify(root, sha="2" * 40)

    def test_tampered_artifact_fails_hash_verification(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp); self._write_bundle(root)
            (root / "nfl_production_validation.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "NFL_CI_ARTIFACT_HASH_MISMATCH"):
                self._verify(root)

    def test_model_artifact_must_be_present_and_exact_identity(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp); self._write_bundle(root)
            manifest_path = root / "nfl_promotion_evidence_manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["artifacts"] = [r for r in manifest["artifacts"] if r["path"] != "nfl_m2_model.json"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "NFL_CI_REQUIRED_ARTIFACT_MISSING:nfl_m2_model.json"):
                self._verify(root)


if __name__ == "__main__":
    unittest.main()
