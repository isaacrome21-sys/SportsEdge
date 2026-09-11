import json
from pathlib import Path
import tempfile
import unittest

from sportsedge.football_prop_code_surface import (
    NFLPropCodeSurfaceError,
    load_and_verify_nfl_prop_code_surface,
    nfl_prop_runtime_code_status,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config/nfl_prop_code_surface_v1.json"
MANIFEST_SHA256 = "6d59edd86845a63625fd0c55be311891622f315034bc06274fb38a30aa92f280"
FIT_SHA = "5dfa29347bed608771e6a2395ce8e894dbfdd881"


class NFLPropCodeSurfaceTests(unittest.TestCase):
    def test_checked_in_surface_verifies_exactly(self):
        out = load_and_verify_nfl_prop_code_surface(
            MANIFEST,
            repo_root=ROOT,
            expected_sha256=MANIFEST_SHA256,
            expected_fit_git_sha=FIT_SHA,
        )
        self.assertEqual(out["fit_git_sha"], FIT_SHA)
        self.assertEqual(out["manifest_sha256"], MANIFEST_SHA256)
        self.assertGreaterEqual(out["file_count"], 20)

    def test_unrelated_runtime_commit_is_allowed_after_surface_verification(self):
        freeze = {
            "code_git_sha": FIT_SHA,
            "code_surface_manifest_path": "config/nfl_prop_code_surface_v1.json",
            "code_surface_sha256": MANIFEST_SHA256,
        }
        out = nfl_prop_runtime_code_status("b" * 40, freeze, repo_root=ROOT)
        self.assertTrue(out["compatible"])
        self.assertEqual(out["fit_git_sha"], FIT_SHA)
        self.assertEqual(out["runtime_git_sha"], "b" * 40)
        self.assertEqual(out["manifest_sha256"], MANIFEST_SHA256)

    def test_changed_declared_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "model.py"
            source.write_text("x = 1\n", encoding="utf-8")
            payload = {
                "schema_version": "NFL_PROP_CODE_SURFACE_V1",
                "fit_git_sha": FIT_SHA,
                "files": {"model.py": "0" * 40},
            }
            manifest = root / "surface.json"
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                NFLPropCodeSurfaceError,
                "NFL_PROP_CODE_SURFACE_MISMATCH:model.py",
            ):
                load_and_verify_nfl_prop_code_surface(manifest, repo_root=root)

    def test_manifest_hash_and_fit_sha_are_independently_bound(self):
        with self.assertRaisesRegex(
            NFLPropCodeSurfaceError, "NFL_PROP_CODE_SURFACE_MANIFEST_SHA256_MISMATCH"
        ):
            load_and_verify_nfl_prop_code_surface(
                MANIFEST,
                repo_root=ROOT,
                expected_sha256="0" * 64,
                expected_fit_git_sha=FIT_SHA,
            )
        with self.assertRaisesRegex(
            NFLPropCodeSurfaceError, "NFL_PROP_CODE_SURFACE_FIT_GIT_SHA_MISMATCH"
        ):
            load_and_verify_nfl_prop_code_surface(
                MANIFEST,
                repo_root=ROOT,
                expected_sha256=MANIFEST_SHA256,
                expected_fit_git_sha="a" * 40,
            )

    def test_legacy_binding_still_requires_exact_repo_sha(self):
        freeze = {"code_git_sha": FIT_SHA}
        exact = nfl_prop_runtime_code_status(FIT_SHA, freeze, repo_root=ROOT)
        self.assertEqual(exact["mode"], "LEGACY_EXACT_REPO_SHA")
        with self.assertRaisesRegex(
            NFLPropCodeSurfaceError, "NFL_PROP_CODE_SURFACE_LEGACY_GIT_SHA_MISMATCH"
        ):
            nfl_prop_runtime_code_status("b" * 40, freeze, repo_root=ROOT)

    def test_incomplete_surface_binding_fails_closed(self):
        with self.assertRaisesRegex(
            NFLPropCodeSurfaceError, "NFL_PROP_CODE_SURFACE_BINDING_INCOMPLETE"
        ):
            nfl_prop_runtime_code_status(
                "b" * 40,
                {"code_git_sha": FIT_SHA, "code_surface_manifest_path": "surface.json"},
                repo_root=ROOT,
            )


if __name__ == "__main__":
    unittest.main()
