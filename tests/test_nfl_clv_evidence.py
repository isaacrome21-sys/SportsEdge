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
            "game_start_ts": "2026-09-11T00:20:00+00:00",
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
            "close_ts": "2026-09-11T00:15:00+00:00",
            "game_start_ts": "2026-09-11T00:20:00+00:00",
            "game_id": "2026_01_AAA_BBB",
            "sport": "nfl",
            "market": "spread",
            "side": "AAA",
            "book": "book",
            "closing_line": -3.5,
            "closing_price": -110,
            # This probability is an alternate closing quote at the original
            # decision threshold, not the no-vig probability at -3.5.
            "closing_novig_prob": 0.52,
            "probability_line": -3.0,
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

    def test_exact_code_sha_probability_reference_and_forward_contract_are_persisted(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            sha = "1" * 40
            result, out = self._run(root, self._decision(sha), self._close(sha), sha)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["code_git_sha"], sha)
            self.assertEqual(payload["decision_count"], 1)
            self.assertEqual(payload["markets"]["spread"]["logged_plays"], 1)
            self.assertEqual(payload["clv_probability_reference"], "DECISION_THRESHOLD")
            self.assertEqual(payload["forward_time_contract"], "PREGAME_DECISION_TO_PREGAME_CLOSE")
            self.assertEqual(payload["close_book_contract"], "SAME_BOOK_AS_DECISION")

    def test_moved_line_without_decision_threshold_probability_fails_closed(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            sha = "1" * 40
            close = self._close(sha)
            close.pop("probability_line")
            result, _ = self._run(root, self._decision(sha), close, sha)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("CLV_REFERENCE_LINE_MISMATCH", result.stdout + result.stderr)

    def test_close_after_game_start_cannot_count_as_forward_clv(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            sha = "1" * 40
            close = self._close(sha)
            close["close_ts"] = "2026-09-11T00:21:00+00:00"
            result, _ = self._run(root, self._decision(sha), close, sha)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("NFL_CLV_CLOSE_NOT_PREGAME", result.stdout + result.stderr)

    def test_close_must_be_after_decision(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            sha = "1" * 40
            close = self._close(sha)
            close["close_ts"] = "2026-09-10T22:59:00+00:00"
            result, _ = self._run(root, self._decision(sha), close, sha)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("NFL_CLV_CLOSE_NOT_AFTER_DECISION", result.stdout + result.stderr)

    def test_close_must_match_decision_book(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            sha = "1" * 40
            close = self._close(sha)
            close["book"] = "other-book"
            result, _ = self._run(root, self._decision(sha), close, sha)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("NFL_CLV_CLOSE_BOOK_MISMATCH", result.stdout + result.stderr)

    def test_game_start_identity_must_match_both_logs(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            sha = "1" * 40
            close = self._close(sha)
            close["game_start_ts"] = "2026-09-11T00:30:00+00:00"
            result, _ = self._run(root, self._decision(sha), close, sha)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("NFL_CLV_GAME_START_MISMATCH", result.stdout + result.stderr)

    def test_mixed_code_sha_fails_closed(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            expected = "1" * 40
            result, _ = self._run(root, self._decision(expected), self._close("2" * 40), expected)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("NFL_CLV_CODE_SHA_MISMATCH", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
