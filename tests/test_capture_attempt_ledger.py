"""Fail-closed contracts for append-only capture-stage receipts."""
import json
import os
from unittest.mock import patch
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.capture_attempt_ledger import AttemptLedger


class LedgerTests(unittest.TestCase):
    def test_short_writes_complete_json_record_before_credit(self):
        with tempfile.TemporaryDirectory() as tmp:
            with AttemptLedger(tmp, game_id="g", capture_kind="TEST",
                               due_utc="2026-01-01T00:00:00Z") as ledger:
                real_write = os.write
                with patch("scripts.capture_attempt_ledger.os.write",
                           side_effect=lambda fd, data: real_write(fd, data[:8])):
                    ledger.record("dispatch")
                rows = [json.loads(line) for line in ledger.path.read_text().splitlines()]
                self.assertEqual(rows[-1]["stage"], "dispatch")
                self.assertIn("dispatch", ledger._seen)

    def test_failed_writes_poison_attempt_without_stage_credit(self):
        for failure in ("zero", "error", "fsync"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                with AttemptLedger(tmp, game_id="g", capture_kind="TEST",
                                   due_utc="2026-01-01T00:00:00Z") as ledger:
                    target = "os.fsync" if failure == "fsync" else "os.write"
                    kwargs = ({"return_value": 0} if failure == "zero" else
                              {"side_effect": OSError("disk failure")})
                    with patch("scripts.capture_attempt_ledger." + target, **kwargs):
                        with self.assertRaises(OSError):
                            ledger.record("dispatch")
                    self.assertNotIn("dispatch", ledger._seen)
                    with self.assertRaises(ValueError):
                        ledger.record("failure", detail="cannot append to damaged attempt")

    def test_success_has_six_distinct_durable_stages(self):
        with tempfile.TemporaryDirectory() as tmp:
            before = datetime.now(timezone.utc)
            with AttemptLedger(tmp, game_id="g1", capture_kind="FINAL",
                               due_utc="2026-10-26T19:00:00Z",
                               window_end_utc=(before + timedelta(minutes=30)).isoformat()) as ledger:
                ledger.record("dispatch")
                with self.assertRaisesRegex(ValueError, "authenticated source"):
                    ledger.record("source_capture")
                ledger.record("source_capture", raw=b"authentic fixture",
                              source_timestamp_utc="2026-10-26T19:00:01Z")
                ledger.record("ingestion")
                ledger.record("durable_write", receipt_locator="data/immutable/receipt.json")
                ledger.record("card_delivery", receipt_locator="issue/123#comment-456")
                path = ledger.path
            events = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual([e["stage"] for e in events], [
                "scheduled_due", "dispatch", "source_capture", "ingestion", "durable_write",
                "card_delivery",
            ])
            self.assertEqual(len({e["attempt_id"] for e in events}), 1)
            self.assertEqual(len(events[2]["sha256"]), 64)
            self.assertTrue(all(e["scheduled_due_utc"] == "2026-10-26T19:00:00.000000Z"
                                for e in events))
            recorded = datetime.fromisoformat(events[0]["observed_at_utc"].replace("Z", "+00:00"))
            self.assertGreaterEqual(recorded, before)
            self.assertNotEqual(events[0]["observed_at_utc"], events[0]["scheduled_due_utc"])

    def test_failed_attempt_remains_on_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            with AttemptLedger(tmp, game_id="g2", capture_kind="FINAL",
                               due_utc="2026-10-26T19:00:00Z") as ledger:
                ledger.record("dispatch")
                path = ledger.path
            self.assertEqual(json.loads(path.read_text().splitlines()[-1])["stage"], "failure")

    def test_no_delivery_without_durable_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            with AttemptLedger(tmp, game_id="g3", capture_kind="OPENER",
                               due_utc="2026-10-26T19:00:00Z") as ledger:
                with self.assertRaisesRegex(ValueError, "durable write"):
                    ledger.record("card_delivery")

    def test_naive_time_refused(self):
        from scripts.capture_attempt_ledger import utc_stamp
        with self.assertRaises(ValueError):
            utc_stamp(datetime(2026, 10, 26))

    def test_source_timestamp_must_be_parseable_aware_and_observed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with AttemptLedger(tmp, game_id="g", capture_kind="FINAL",
                               due_utc="2026-10-26T19:00:00Z") as ledger:
                ledger.record("dispatch")
                for source_time in ("not-a-time", "2026-10-26T19:00:01",
                                    "9999-12-31T23:59:59Z"):
                    with self.subTest(source_time=source_time), self.assertRaises(ValueError):
                        ledger.record("source_capture", raw=b"record",
                                      source_timestamp_utc=source_time)
                self.assertNotIn("source_capture", ledger._seen)

    def test_empty_raw_source_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with AttemptLedger(tmp, game_id="g", capture_kind="FINAL",
                               due_utc="2026-10-26T19:00:00Z") as ledger:
                ledger.record("dispatch")
                with self.assertRaisesRegex(ValueError, "authenticated source"):
                    ledger.record("source_capture", raw=b"",
                                  source_timestamp_utc="2026-10-26T19:00:01Z")

    def test_ingestion_and_archive_stage_order_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            with AttemptLedger(tmp, game_id="g", capture_kind="FINAL",
                               due_utc="2026-10-26T19:00:00Z") as ledger:
                ledger.record("dispatch")
                with self.assertRaisesRegex(ValueError, "CAPTURE_STAGE_OUT_OF_ORDER"):
                    ledger.record("ingestion")
                ledger.record("source_capture", raw=b"source",
                              source_timestamp_utc="2026-10-26T19:00:01Z")
                with self.assertRaisesRegex(ValueError, "CAPTURE_STAGE_OUT_OF_ORDER"):
                    ledger.record("durable_write", receipt_locator="data/receipt")

    def test_issue_locator_required_for_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            with AttemptLedger(tmp, game_id="g", capture_kind="FINAL",
                               due_utc="2026-10-26T19:00:00Z") as ledger:
                ledger.record("dispatch")
                ledger.record("source_capture", raw=b"source",
                              source_timestamp_utc="2026-10-26T19:00:01Z")
                ledger.record("ingestion")
                ledger.record("durable_write", receipt_locator="data/receipt")
                with self.assertRaisesRegex(ValueError, "issue locator"):
                    ledger.record("card_delivery")

    def test_after_window_delivery_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=1)
            due = cutoff - timedelta(minutes=10)
            with AttemptLedger(tmp, game_id="g", capture_kind="FINAL",
                               due_utc=due.isoformat(),
                               window_end_utc=cutoff.isoformat()) as ledger:
                ledger.record("dispatch")
                ledger.record("source_capture", raw=b"source",
                              source_timestamp_utc="2026-10-26T19:00:01Z")
                ledger.record("ingestion")
                ledger.record("durable_write", receipt_locator="data/receipt")
                with self.assertRaisesRegex(ValueError, "LATE_CAPTURE"):
                    ledger.record("card_delivery", receipt_locator="issue/7")
                self.assertNotIn("card_delivery", ledger._seen)

    def test_direct_observed_time_override_is_not_in_public_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            with AttemptLedger(tmp, game_id="g", capture_kind="FINAL",
                               due_utc="2026-10-26T19:00:00Z") as ledger:
                with self.assertRaises(TypeError):
                    ledger.record("dispatch", at=datetime(2026, 10, 26))
                self.assertNotIn("dispatch", ledger._seen)

    def test_delivery_requires_a_frozen_write_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            with AttemptLedger(tmp, game_id="g", capture_kind="FINAL",
                               due_utc="2026-10-26T19:00:00Z") as ledger:
                ledger.record("dispatch")
                ledger.record("source_capture", raw=b"quoted bytes",
                              source_timestamp_utc="2026-10-26T19:00:01Z")
                ledger.record("ingestion")
                ledger.record("durable_write", receipt_locator="data/receipt")
                with self.assertRaisesRegex(ValueError, "CAPTURE_WINDOW_REQUIRED"):
                    ledger.record("card_delivery", receipt_locator="issue/9")
                self.assertNotIn("card_delivery", ledger._seen)


    def test_constructor_receipt_failure_closes_open_fd(self):
        with tempfile.TemporaryDirectory() as tmp:
            real_close = os.close
            closed = []

            def tracking_close(fd):
                closed.append(fd)
                return real_close(fd)

            with patch("scripts.capture_attempt_ledger.os.close",
                       side_effect=tracking_close):
                with patch("scripts.capture_attempt_ledger.os.fsync",
                           side_effect=OSError("disk failure")):
                    with self.assertRaises(OSError):
                        AttemptLedger(tmp, game_id="g", capture_kind="TEST",
                                      due_utc="2026-01-01T00:00:00Z")
            self.assertEqual(len(closed), 1)

    def test_explicit_close_failure_still_releases_fd(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = AttemptLedger(tmp, game_id="g", capture_kind="TEST",
                                   due_utc="2026-01-01T00:00:00Z")
            fd = ledger._fd
            with patch("scripts.capture_attempt_ledger.os.write",
                       side_effect=OSError("disk failure")):
                with self.assertRaises(OSError):
                    ledger.close()
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_context_exit_failure_still_releases_fd(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = AttemptLedger(tmp, game_id="g", capture_kind="TEST",
                                   due_utc="2026-01-01T00:00:00Z")
            fd = ledger._fd
            with patch("scripts.capture_attempt_ledger.os.write",
                       side_effect=OSError("disk failure")):
                with self.assertRaises(OSError):
                    ledger.__exit__(None, None, None)
            with self.assertRaises(OSError):
                os.fstat(fd)



if __name__ == "__main__":
    unittest.main()
