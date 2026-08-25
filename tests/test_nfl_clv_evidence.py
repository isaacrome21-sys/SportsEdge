import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from sportsedge.sports.nfl.m2 import NFL_M2_FEATURE_CONTRACT, PRODUCTION_NFL_M2_MODEL_ID


class NFLCLVEvidenceTests(unittest.TestCase):
    def _decision(self, git_sha: str) -> dict:
        return {
            "decision_ts": "2026-09-10T23:00:00+00:00",
            "game_id": "2026_01_AAA_BBB",
            "sport": "nfl",
            "market": "spread",
            "side": "AAA",
            "book": "book",
            "line_at_decision": -3.0,
            "price_at_decision": -110,
            "model_prob": 0.56,
            "novig_prob": 0.50,
            "ev": 0.06,
            "kelly_frac": 0.02,
            "stake_units": 0.5,
            "gate_result": "OFFICIAL",
            "model_id": PRODUCTION_NFL_M2_MODEL_ID,
            "feature_contract": NFL_M2_FEATURE_CONTRACT,
            "code_git_sha": git_sha,
        }

    def _close(self, git_sha: str) -> dict:
        return {
            "game_id": "2026_01_AAA_BBB",
            "sport": "nfl",
            "market": "spread",
            "side": "AAA",
            "closing_line": -3.5,
            "closing_price": -110,
            "closing_novig_prob": 0.52,
            "model_id": PRODUCTION_NFL_M2_MODEL_ID,
            "feature_contract": NFL_M2_FEATURE_CONTRACT,
            "code_git_sha": git_sha,
        }

    def _run(self, root: Path, decision: dict, close: dict, expected_sha: str):
        decisions = root / "decisions.jsonl"
        closes = root / "closes.jsonl"
        out = root / "out.json"
        decisions.write_text(json.dumps(decision) + "\n", encoding="utf-8")
        closes.write_text(json.dumps(close) + "\n", encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                "scripts/build_nfl_clv_evidence.py",
                "--decisions", str(decisions),
                "--closes", str(closes),
                "--git-sha", expected_sha,
                "--out", str(out),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        return result, out

    def test_exact_code_sha_is_persisted_in_clv_evidence(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            sha = "1" * 40
            result, out = self._run(root, self._decision(sha), self._close(sha), sha)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["code_git_sha"], sha)
            self.assertEqual(payload["decision_count"], 1)
            self.assertEqual(payload["markets"]["spread"]["logged_plays"], 1)

    def test_mixed_code_sha_fails_closed(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            expected = "1" * 40
            result, _ = self._run(root, self._decision(expected), self._close("2" * 40), expected)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("NFL_CLV_CODE_SHA_MISMATCH", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
