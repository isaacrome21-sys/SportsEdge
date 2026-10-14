"""Adversarial clock-bound tests for MLB starter capture (research-only).

Offline: temp files, fake clocks, fake fetchers. Reuses #2166's
RECEIPT_PLAUSIBLE_FLOOR / RECEIPT_CLOCK_SKEW / RECEIPT_MAX_FETCH_SPAN.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from sportsedge.sports.mlb import starter_capture as capture

UTC = timezone.utc
ANCHOR = datetime(2026, 10, 13, 20, 0, tzinfo=UTC)
PLAN = {"game_pk": 849001, "official_date": "2026-10-13",
        "game_date_utc": "2026-10-13T23:05:00Z", "game_type": "R",
        "slots": [{"slot_id": "T-30M", "due_at_utc": "2026-10-13T22:35:00Z"}]}


def _rec(**kw):
    r = {"record_type": "SNAPSHOT", "game_pk": 849001, "slot_id": "T-30M",
         "record_status": "OBSERVED", "captured_at_utc": "2026-10-13T19:59:00+00:00"}
    r.update(kw)
    return r


class _Clock:
    def __init__(self, *values):
        self.values = list(values)

    def __call__(self):
        return self.values.pop(0) if len(self.values) > 1 else self.values[0]


def _boom(url):
    raise OSError("offline")


class CaptureSnapshotClockTests(unittest.TestCase):
    def _snap(self, clock, anchor=None, fetcher=_boom):
        return capture.capture_snapshot(PLAN, "T-30M", fetcher=fetcher,
                                        clock=clock, anchor=anchor)

    def test_y2k_fetch_start_refused(self):
        with self.assertRaisesRegex(capture.StarterCaptureError, "IMPLAUSIBLY_OLD:fetch_started_at"):
            self._snap(_Clock(datetime(2000, 1, 1, tzinfo=UTC)))

    def test_y2k_receipt_refused(self):
        with self.assertRaisesRegex(capture.StarterCaptureError, "IMPLAUSIBLY_OLD|WENT_BACKWARDS"):
            self._snap(_Clock(ANCHOR, datetime(2000, 1, 1, tzinfo=UTC)))

    def test_just_before_floor_refused(self):
        with self.assertRaisesRegex(capture.StarterCaptureError, "IMPLAUSIBLY_OLD"):
            self._snap(_Clock(datetime(2019, 12, 31, 23, 59, 59, tzinfo=UTC)))

    def test_future_beyond_skew_refused_with_anchor(self):
        with self.assertRaisesRegex(capture.StarterCaptureError, "IN_FUTURE"):
            self._snap(_Clock(ANCHOR + timedelta(seconds=6)), anchor=lambda: ANCHOR)

    def test_far_future_2099_refused_with_anchor(self):
        with self.assertRaisesRegex(capture.StarterCaptureError, "IN_FUTURE"):
            self._snap(_Clock(datetime(2099, 1, 1, tzinfo=UTC)), anchor=lambda: ANCHOR)

    def test_within_skew_accepted_and_both_times_recorded(self):
        rec = self._snap(_Clock(ANCHOR, ANCHOR + timedelta(seconds=3)),
                         anchor=lambda: ANCHOR)
        self.assertEqual(rec["record_type"], "CAPTURE_ATTEMPT_FAILED")
        self.assertEqual(rec["fetch_started_at_utc"], "2026-10-13T20:00:00+00:00")
        self.assertEqual(rec["attempted_at_utc"], "2026-10-13T20:00:03+00:00")

    def test_clock_backwards_refused(self):
        with self.assertRaisesRegex(capture.StarterCaptureError, "WENT_BACKWARDS"):
            self._snap(_Clock(ANCHOR, ANCHOR - timedelta(seconds=1)))

    def test_fetch_span_over_30s_refused(self):
        with self.assertRaisesRegex(capture.StarterCaptureError, "FETCH_SPAN_UNBOUNDED"):
            self._snap(_Clock(ANCHOR, ANCHOR + timedelta(seconds=31)))

    def test_naive_anchor_refused(self):
        with self.assertRaisesRegex(capture.StarterCaptureError, "CLOCK_UNVERIFIED:anchor"):
            self._snap(_Clock(ANCHOR), anchor=lambda: datetime(2026, 10, 13, 20))

    def test_production_wrapper_supplies_trusted_anchor(self):
        with mock.patch("sportsedge.mlb_source._trusted_now", lambda: ANCHOR), \
             mock.patch.object(capture, "system_utc_now",
                               lambda: datetime(2000, 1, 1, tzinfo=UTC)):
            with self.assertRaisesRegex(capture.StarterCaptureError, "IMPLAUSIBLY_OLD"):
                capture.capture_snapshot_production(PLAN, "T-30M", opener=_boom)


class AppendAndVerifyClockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.cap, self.man = d / "cap.jsonl", d / "man.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def _append(self, rec):
        return capture.append_record(self.cap, self.man, rec, verifier_now=ANCHOR)

    def test_valid_record_appends_and_verifies(self):
        self._append(_rec(fetch_started_at_utc="2026-10-13T19:58:50+00:00"))
        self.assertTrue(capture.verify_capture_chain(self.cap, self.man, verifier_now=ANCHOR)["ok"])

    def test_append_refuses_y2k_record(self):
        with self.assertRaisesRegex(capture.StarterCaptureError, "IMPLAUSIBLY_OLD"):
            self._append(_rec(captured_at_utc="2000-01-01T00:00:00+00:00"))
        self.assertFalse(self.cap.exists() and self.cap.stat().st_size)

    def test_append_refuses_future_record(self):
        with self.assertRaisesRegex(capture.StarterCaptureError, "IN_FUTURE"):
            self._append(_rec(captured_at_utc="2099-01-01T00:00:00+00:00"))

    def test_append_refuses_missing_receipt_stamp(self):
        r = _rec(); del r["captured_at_utc"]
        with self.assertRaisesRegex(capture.StarterCaptureError, "TIMESTAMP_MISSING"):
            self._append(r)

    def test_append_refuses_naive_or_garbage_stamp(self):
        for bad in ("2026-10-13T19:59:00", "not-a-time", 12345):
            with self.assertRaisesRegex(capture.StarterCaptureError, "UNPARSEABLE"):
                self._append(_rec(captured_at_utc=bad))

    def test_append_refuses_y2k_fetch_start(self):
        with self.assertRaisesRegex(capture.StarterCaptureError, "IMPLAUSIBLY_OLD:fetch_started_at_utc"):
            self._append(_rec(fetch_started_at_utc="2000-01-01T00:00:00+00:00"))

    def test_append_refuses_unbounded_span(self):
        with self.assertRaisesRegex(capture.StarterCaptureError, "FETCH_SPAN_UNBOUNDED"):
            self._append(_rec(fetch_started_at_utc="2026-10-13T19:50:00+00:00"))

    def test_attempt_failed_record_needs_attempt_stamp(self):
        with self.assertRaisesRegex(capture.StarterCaptureError, "TIMESTAMP_MISSING:attempted_at_utc"):
            self._append({"record_type": "CAPTURE_ATTEMPT_FAILED", "game_pk": 1, "slot_id": "x"})

    def _forge(self, rec):
        """Write a correctly-chained pair that bypasses append_record."""
        line = capture.canonical_line(rec)
        digest = capture._sha256_hex(line)
        prev = capture.GENESIS_CHAIN_SHA256
        chain = capture._sha256_hex(f"{prev}:{digest}".encode())
        entry = {"schema": capture.SCHEMA_MANIFEST_ENTRY, "seq": 1,
                 "record_sha256": digest, "record_type": rec.get("record_type"),
                 "game_pk": rec.get("game_pk"), "slot_id": rec.get("slot_id"),
                 "prev_chain_sha256": prev, "chain_sha256": chain}
        self.cap.write_bytes(line + b"\n")
        self.man.write_bytes(capture.canonical_line(entry) + b"\n")

    def test_verify_fails_closed_on_hash_valid_y2k_record(self):
        self._forge(_rec(captured_at_utc="2000-01-01T00:00:00+00:00"))
        out = capture.verify_capture_chain(self.cap, self.man, verifier_now=ANCHOR)
        self.assertFalse(out["ok"])
        self.assertIn("IMPLAUSIBLY_OLD", out["failure"]["reason"])

    def test_verify_fails_closed_on_hash_valid_future_record(self):
        self._forge(_rec(captured_at_utc="2026-10-13T20:00:06+00:00"))
        out = capture.verify_capture_chain(self.cap, self.man, verifier_now=ANCHOR)
        self.assertFalse(out["ok"])
        self.assertIn("IN_FUTURE", out["failure"]["reason"])

    def test_append_refuses_to_extend_chain_with_y2k_record(self):
        self._forge(_rec(captured_at_utc="2000-01-01T00:00:00+00:00"))
        with self.assertRaisesRegex(capture.StarterCaptureError, "PREAPPEND_INVALID"):
            self._append(_rec())

    def test_verify_default_uses_trusted_clock(self):
        self._forge(_rec(captured_at_utc="2099-01-01T00:00:00+00:00"))
        out = capture.verify_capture_chain(self.cap, self.man)
        self.assertFalse(out["ok"])


if __name__ == "__main__":
    unittest.main()
