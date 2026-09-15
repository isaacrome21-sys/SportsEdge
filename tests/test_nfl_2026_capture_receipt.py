import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scripts.build_nfl_2026_capture_receipt as receipt_builder


class NFL2026CaptureReceiptTests(unittest.TestCase):
    def test_capture_record_without_lock_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            capture_root = root / "captures"
            record = capture_root / "week02" / "opener.json"
            record.parent.mkdir(parents=True)
            record.write_text('{"capture_kind":"OPENER"}\n', encoding="utf-8")

            policy = root / "policy.json"
            policy.write_text('{}\n', encoding="utf-8")
            script = root / "capture.py"
            script.write_text('pass\n', encoding="utf-8")
            workflow = root / "capture.yml"
            workflow.write_text('name: capture\n', encoding="utf-8")
            config = root / "config.json"
            config.write_text(json.dumps({
                "capture_config_version": "test",
                "policy_path": str(policy),
                "output_dir": str(capture_root),
                "bookmaker": "draftkings",
                "first_week": 2,
            }), encoding="utf-8")

            out = root / "receipt.json"
            with patch.object(receipt_builder, "CAPTURE_SCRIPT", script), patch.object(
                receipt_builder, "CAPTURE_WORKFLOW", workflow
            ):
                receipt = receipt_builder.build(config, out)

            self.assertEqual(receipt["metadata"]["capture_record_count"], 1)
            self.assertEqual(
                receipt["metadata"]["capture_lock_status"],
                "LOCK_MISSING_WITH_CAPTURE_RECORDS",
            )
            self.assertIn(
                "capture_lock.json", receipt["metadata"]["capture_lock_mismatches"]
            )


if __name__ == "__main__":
    unittest.main()
