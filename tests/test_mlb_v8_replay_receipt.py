import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_mlb_v8_replay_receipt import build


class MLBV8ReplayReceiptTests(unittest.TestCase):
    def test_binds_policy_inputs_and_outputs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            policy = root / "policy.json"
            inputs = root / "inputs"
            archive = root / "archive"
            inputs.mkdir()
            archive.mkdir()

            policy.write_text('{"policy":"frozen"}\n', encoding="utf-8")
            (inputs / "snapshot.json").write_text('{"odds":1}\n', encoding="utf-8")
            (archive / "manifest.json").write_text('{"manifest":1}\n', encoding="utf-8")
            (archive / "gap_report.json").write_text('[]\n', encoding="utf-8")

            first = build(inputs, archive, policy)
            second = build(inputs, archive, policy)
            self.assertEqual(first["receipt_sha256"], second["receipt_sha256"])
            self.assertFalse(first["metadata"]["forward_holdout_replacement_allowed"])
            self.assertFalse(first["promotion_authority"])

            names = {row["path"] for row in first["files"]}
            self.assertIn("policy/mlb_v8_evidence_policy.json", names)
            self.assertIn("inputs/snapshot.json", names)
            self.assertIn("outputs/manifest.json", names)
            self.assertIn("outputs/gap_report.json", names)

            stored = json.loads((archive / "receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(stored["receipt_sha256"], first["receipt_sha256"])

            (inputs / "snapshot.json").write_text('{"odds":2}\n', encoding="utf-8")
            changed = build(inputs, archive, policy)
            self.assertNotEqual(changed["receipt_sha256"], first["receipt_sha256"])


if __name__ == "__main__":
    unittest.main()
