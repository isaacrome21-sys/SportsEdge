import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "run_football_auto_bundle_tested",
    ROOT / "scripts/run_football_auto_bundle.py",
)
BUNDLE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(BUNDLE)


class FootballAutoBundleFreshnessTests(unittest.TestCase):
    def _path(self, root: Path) -> Path:
        return root / "child.json"

    def _write(self, path: Path, *, model_p=0.61, status="SUCCESS", blocker=None):
        payload = {
            "status": status,
            "report": {
                "run_status": status,
                "results": [{
                    "market": "SPREAD",
                    "model_p": model_p,
                    "bet_status": "BLOCKED",
                    "model_candidate_status": "READY",
                }],
            },
        }
        if blocker is not None:
            payload["blocker"] = blocker
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_unchanged_old_card_is_never_reused(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._path(Path(td))
            self._write(path)
            before = BUNDLE._stamp(path)
            rows, payload = BUNDLE._load(path, "GAME", 2, before)
            self.assertEqual(payload, {})
            self.assertEqual(len(rows), 1)
            self.assertIsNone(rows[0]["model_p"])
            self.assertEqual(rows[0]["bet_status"], "BLOCKED")
            self.assertEqual(rows[0]["reason"], "GAME_OUTPUT_NOT_REFRESHED")

    def test_nonzero_child_exit_cannot_export_model_rows(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._path(Path(td))
            self._write(path, blocker="NFL_AUTO_FROZEN_MODEL_ARTIFACT_REQUIRED")
            rows, payload = BUNDLE._load(path, "GAME", 2, None)
            self.assertEqual(payload["blocker"], "NFL_AUTO_FROZEN_MODEL_ARTIFACT_REQUIRED")
            self.assertEqual(len(rows), 1)
            self.assertIsNone(rows[0]["model_p"])
            self.assertEqual(rows[0]["bet_status"], "BLOCKED")
            self.assertEqual(rows[0]["reason"], "NFL_AUTO_FROZEN_MODEL_ARTIFACT_REQUIRED")

    def test_refreshed_success_card_is_consumed(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._path(Path(td))
            self._write(path, model_p=0.58)
            rows, payload = BUNDLE._load(path, "GAME", 0, None)
            self.assertEqual(payload["status"], "SUCCESS")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["model_p"], 0.58)
            self.assertEqual(rows[0]["run_it_lane"], "GAME")

    def test_missing_child_output_is_explicit_blocker(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._path(Path(td))
            rows, payload = BUNDLE._load(path, "PLAYER_PROPS", 2, None)
            self.assertEqual(payload, {})
            self.assertEqual(rows[0]["reason"], "PLAYER_PROPS_OUTPUT_MISSING")
            self.assertIsNone(rows[0]["model_p"])

    def test_cfb_prop_lane_is_explicit_no_engine(self):
        executable, reason = BUNDLE._prop_lane_state("CFB")
        self.assertFalse(executable)
        self.assertIn("NO_ENGINE", reason)

    def test_nfl_prop_lane_is_explicit_no_engine(self):
        executable, reason = BUNDLE._prop_lane_state("NFL")
        self.assertFalse(executable)
        self.assertIn("NO_ENGINE", reason)


if __name__ == "__main__":
    unittest.main()
