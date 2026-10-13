"""Research starter binder must reject uncommitted write-ahead capture stores.

Offline adversarial assertions: hash chain and raw bytes may each verify,
while the intent journal is still pending or corrupt. No network, prices,
history capture, or capture activation are involved.
"""
from datetime import datetime, timezone
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from sportsedge.mlb_pit_binding import load_research_starter_binding


class ResearchStarterIntentGateTests(TestCase):
    def _bind(self):
        return load_research_starter_binding(
            capture_path=Path("/nonexistent/test-capture.jsonl"),
            manifest_path=Path("/nonexistent/test-manifest.jsonl"),
            raw_dir=Path("/nonexistent/raw"),
            receipt_root=Path("/nonexistent/receipts"),
            game_pk=712345,
            as_of=datetime(2026, 10, 13, 18, tzinfo=timezone.utc),
            plan_first_pitch_utc="2026-10-14T00:00:00+00:00",
        )

    def test_pending_intent_blocks_even_when_chain_and_raw_each_verify(self):
        with (
            patch("sportsedge.sports.mlb.starter_capture.verify_capture_chain",
                  return_value={"ok": True, "failure": None}),
            patch("sportsedge.sports.mlb.starter_capture.verify_raw_store",
                  return_value={"ok": True, "failure": None}),
            patch("sportsedge.sports.mlb.starter_capture.verify_capture_store",
                  return_value={"ok": False, "failure": {"reason": "INTENT_UNCOMMITTED"}}),
            patch("sportsedge.mlb_source.verify_receipt_journal") as receipts,
        ):
            out = self._bind()
            self.assertEqual(out["binding_status"], "BLOCKED")
            self.assertIn("INTENT_UNCOMMITTED", out["block_reason"])
            self.assertFalse(out["pricing_authorized"])
            self.assertFalse(out["betting_authorized"])
            receipts.assert_not_called()

    def test_corrupt_intent_reader_exception_blocks_not_crashes(self):
        with (
            patch("sportsedge.sports.mlb.starter_capture.verify_capture_chain",
                  return_value={"ok": True, "failure": None}),
            patch("sportsedge.sports.mlb.starter_capture.verify_raw_store",
                  return_value={"ok": True, "failure": None}),
            patch("sportsedge.sports.mlb.starter_capture.verify_capture_store",
                  side_effect=ValueError("corrupted intent")),
            patch("sportsedge.mlb_source.verify_receipt_journal") as receipts,
        ):
            out = self._bind()
            self.assertEqual(out["binding_status"], "BLOCKED")
            self.assertIn("CAPTURE_STORE_UNVERIFIED", out["block_reason"])
            receipts.assert_not_called()

    def test_malformed_verifier_result_blocks_not_crashes(self):
        with (
            patch("sportsedge.sports.mlb.starter_capture.verify_capture_chain",
                  return_value={"ok": True, "failure": None}),
            patch("sportsedge.sports.mlb.starter_capture.verify_raw_store",
                  return_value={"ok": True, "failure": None}),
            patch("sportsedge.sports.mlb.starter_capture.verify_capture_store",
                  return_value=None),
            patch("sportsedge.mlb_source.verify_receipt_journal") as receipts,
        ):
            out = self._bind()
            self.assertEqual(out["binding_status"], "BLOCKED")
            self.assertIn("INVALID_VERIFIER_RESULT", out["block_reason"])
            receipts.assert_not_called()
