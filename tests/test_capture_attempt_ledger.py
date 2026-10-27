"""Fail-closed contracts for capture attempt stage ledger."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from scripts.capture_attempt_ledger import AttemptLedger


class LedgerTests(unittest.TestCase):
    def test_success_has_five_distinct_durable_stages(self):
        with tempfile.TemporaryDirectory() as tmp:
            with AttemptLedger(tmp, game_id="g1", capture_kind="FINAL", due_utc="2026-10-26T19:00:00Z") as ledger:
                ledger.record("dispatch")
                with self.assertRaisesRegex(ValueError, "authenticated source"):
                    ledger.record("source_capture")
                ledger.record("source_capture", raw=b"authentic fixture", source_timestamp_utc="2026-10-26T19:00:01Z")
                ledger.record("ingestion")
                ledger.record("durable_write", receipt_locator="data/immutable/receipt.json")
                ledger.record("card_delivery", receipt_locator="issue/123#comment-456")
                path = ledger.path
            events = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual([e["stage"] for e in events], [
                "scheduled_due", "dispatch", "source_capture", "ingestion", "durable_write", "card_delivery"])
            self.assertEqual(len({e["attempt_id"] for e in events}), 1)
            self.assertEqual(len(events[2]["sha256"]), 64)

    def test_failed_attempt_remains_on_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            with AttemptLedger(tmp, game_id="g2", capture_kind="FINAL", due_utc="2026-10-26T19:00:00Z") as ledger:
                ledger.record("dispatch")
                path = ledger.path
            self.assertEqual(json.loads(path.read_text().splitlines()[-1])["stage"], "failure")

    def test_no_delivery_without_durable_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            with AttemptLedger(tmp, game_id="g3", capture_kind="OPENER", due_utc="2026-10-26T19:00:00Z") as ledger:
                with self.assertRaisesRegex(ValueError, "durable write"):
                    ledger.record("card_delivery")

    def test_naive_time_refused(self):
        from scripts.capture_attempt_ledger import utc_stamp
        with self.assertRaises(ValueError):
            utc_stamp(datetime(2026, 10, 26))


if __name__ == "__main__":
    unittest.main()
