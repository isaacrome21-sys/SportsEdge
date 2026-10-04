import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from sportsedge.sports.nfl.code_surface import (
    NFLCodeSurfaceError,
    load_and_verify_nfl_m2_code_surface,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config/nfl_m2_code_surface_v1.json"
MANIFEST_SHA256 = "e3296a45fe07521f3851986afc4554e161e4c3183ee2b9c75e5e4ad5ddea67f2"
FIT_SHA = "d0609a44cb3c379fcb4d09afc9249dd8f9b54ef9"


def _load_auto_module():
    spec = importlib.util.spec_from_file_location("run_nfl_auto_tested", ROOT / "scripts/run_nfl_auto.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class NFLM2CodeSurfaceTests(unittest.TestCase):
    def test_checked_in_surface_verifies_exactly(self):
        out = load_and_verify_nfl_m2_code_surface(
            MANIFEST,
            repo_root=ROOT,
            expected_sha256=MANIFEST_SHA256,
            expected_fit_git_sha=FIT_SHA,
        )
        self.assertEqual(out["fit_git_sha"], FIT_SHA)
        self.assertEqual(out["manifest_sha256"], MANIFEST_SHA256)
        self.assertGreaterEqual(out["file_count"], 10)

    def test_changed_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "model.py"
            source.write_text("x = 1\n", encoding="utf-8")
            payload = {
                "schema_version": "NFL_M2_CODE_SURFACE_V1",
                "fit_git_sha": FIT_SHA,
                "files": {"model.py": "0" * 40},
            }
            manifest = root / "surface.json"
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(NFLCodeSurfaceError, "NFL_M2_CODE_SURFACE_MISMATCH:model.py"):
                load_and_verify_nfl_m2_code_surface(manifest, repo_root=root)

    def test_manifest_hash_is_independently_bound(self):
        with self.assertRaisesRegex(NFLCodeSurfaceError, "MANIFEST_SHA256_MISMATCH"):
            load_and_verify_nfl_m2_code_surface(
                MANIFEST,
                repo_root=ROOT,
                expected_sha256="0" * 64,
                expected_fit_git_sha=FIT_SHA,
            )

    def test_frozen_external_binding_may_use_fit_sha_only_after_surface_verification(self):
        auto = _load_auto_module()
        runtime_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip().lower()
        self.assertNotEqual(runtime_sha, FIT_SHA)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "model.json"
            artifact.write_text("{}", encoding="utf-8")
            registry = root / "freeze.json"
            registry.write_text(json.dumps({
                "schema_version": 1,
                "status": "FROZEN",
                "hash_algorithm": "CANONICAL_JSON_SHA256_V1",
                "artifact_path": "relocation-permitted-for-external-freeze.json",
                "artifact_sha256": "a" * 64,
                "code_git_sha": FIT_SHA,
                "compatible_runtime": {
                    "mode": "NFL_M2_CODE_SURFACE_V1",
                    "manifest_path": str(MANIFEST),
                    "manifest_sha256": MANIFEST_SHA256,
                },
            }), encoding="utf-8")
            digest, binding_sha, compatibility = auto._frozen_artifact_hash(
                artifact.resolve(), registry.resolve(), runtime_sha
            )
        self.assertEqual(digest, "a" * 64)
        self.assertEqual(binding_sha, FIT_SHA)
        self.assertEqual(compatibility["manifest_sha256"], MANIFEST_SHA256)

    def test_code_mismatch_without_surface_manifest_stays_blocked(self):
        auto = _load_auto_module()
        runtime_sha = "b" * 40
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "model.json"
            artifact.write_text("{}", encoding="utf-8")
            registry = root / "freeze.json"
            registry.write_text(json.dumps({
                "schema_version": 1,
                "status": "FROZEN",
                "hash_algorithm": "CANONICAL_JSON_SHA256_V1",
                "artifact_path": "model.json",
                "artifact_sha256": "a" * 64,
                "code_git_sha": FIT_SHA,
            }), encoding="utf-8")
            with self.assertRaisesRegex(auto.NFLAutoError, "NFL_AUTO_FROZEN_MODEL_CODE_SHA_MISMATCH"):
                auto._frozen_artifact_hash(artifact.resolve(), registry.resolve(), runtime_sha)


if __name__ == "__main__":
    unittest.main()
