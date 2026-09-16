import csv
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.mlb_pit_replay_metrics import FROZEN_POLICY_GIT_BLOB_SHA, main, score, validate_rows


class ReplayMetricsTests(unittest.TestCase):
    def row(self, **kw):
        r = {
            "decision_id":"d1", "game_id":"g1", "slate_date_ct":"2026-04-01",
            "market":"MONEYLINE", "side":"HOME", "book":"draftkings",
            "model_p":"0.60", "outcome":"1", "decision_no_vig_p":"0.55",
            "close_no_vig_p":"0.57", "net_return":"0.8", "risked_stake":"1",
        }
        r.update(kw)
        return r

    def test_scores_core_metrics(self):
        x = score([self.row()])
        self.assertEqual(x["status"], "SCORED_NOT_PROMOTED")
        self.assertAlmostEqual(x["brier"], 0.16)
        self.assertAlmostEqual(x["log_loss"], 0.5108256237659907)
        self.assertAlmostEqual(x["mean_clv"], 0.02)
        self.assertAlmostEqual(x["roi"], 0.8)
        self.assertAlmostEqual(x["cluster_mean_clv"], 0.02)

    def test_duplicate_decision_fails(self):
        with self.assertRaisesRegex(ValueError, "duplicate decision_id"):
            validate_rows([self.row(), self.row(market="TOTALS")])

    def test_duplicate_composite_observation_fails(self):
        with self.assertRaisesRegex(ValueError, "game/market/side/book"):
            validate_rows([self.row(), self.row(decision_id="d2")])

    def test_bad_probability_fails(self):
        with self.assertRaisesRegex(ValueError, "invalid"):
            score([self.row(model_p="1.1")])

    def test_empty_is_not_evidence(self):
        self.assertEqual(score([])["status"], "NO_EVIDENCE")

    def test_cli_is_byte_deterministic_and_bound(self):
        policy = Path("config/mlb_replay_policy_v1.json")
        data = policy.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()
        self.assertEqual(blob, FROZEN_POLICY_GIT_BLOB_SHA)

        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            inp = td / "replay.csv"
            out1, out2 = td / "a.json", td / "b.json"
            fields = list(self.row().keys())
            with inp.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                w.writeheader()
                w.writerow(self.row())

            for out in (out1, out2):
                argv = ["mlb_pit_replay_metrics.py", "--input", str(inp), "--policy", str(policy),
                        "--policy-commit", "TEST_FROZEN_COMMIT", "--out", str(out)]
                with patch.object(sys, "argv", argv):
                    self.assertEqual(main(), 0)

            self.assertEqual(out1.read_bytes(), out2.read_bytes())
            report = json.loads(out1.read_text(encoding="utf-8"))
            self.assertEqual(report["policy_git_blob_sha"], FROZEN_POLICY_GIT_BLOB_SHA)
            self.assertEqual(report["policy_git_commit"], "TEST_FROZEN_COMMIT")
            self.assertEqual(report["policy_sha256"], hashlib.sha256(data).hexdigest())
            self.assertEqual(report["input_sha256"], hashlib.sha256(inp.read_bytes()).hexdigest())
            self.assertEqual(report["markets"]["MONEYLINE"]["status"], "SCORED_NOT_PROMOTED")
            self.assertTrue(all(v is False for v in report["governance"].values()))


if __name__ == "__main__":
    unittest.main()
