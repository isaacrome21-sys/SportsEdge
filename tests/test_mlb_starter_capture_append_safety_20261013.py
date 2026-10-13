"""Offline regression tests for the MLB research-only paired evidence appender.

These tests use temporary local files only. No network, capture activation,
archival replay, historical odds API calls, pricing or model promotion.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sportsedge.sports.mlb import starter_capture as capture


def _record(n):
    return {"record_type": "SNAPSHOT", "game_pk": 849001,
            "slot_id": f"slot-{n}", "record_status": "OBSERVED"}


class AppendSafetyTests(unittest.TestCase):
    def test_concurrent_writers_have_unique_sequence_and_unbroken_chain(self):
        with tempfile.TemporaryDirectory() as folder:
            a = Path(folder) / "captures.jsonl"
            b = Path(folder) / "manifest.jsonl"
            with ThreadPoolExecutor(max_workers=8) as pool:
                entries = list(pool.map(lambda n: capture.append_record(a, b, _record(n)), range(32)))
            self.assertEqual(sorted(x["seq"] for x in entries), list(range(1, 33)))
            self.assertEqual(len(capture.read_records(a)), 32)
            self.assertTrue(capture.verify_capture_chain(a, b)["ok"])

    def test_partial_second_write_rolls_back_both_files(self):
        with tempfile.TemporaryDirectory() as folder:
            a = Path(folder) / "captures.jsonl"
            b = Path(folder) / "manifest.jsonl"
            capture.append_record(a, b, _record(1))
            before_a, before_b = a.read_bytes(), b.read_bytes()
            original_append = capture._append_line

            def fault(path, line):
                if path == b:
                    with b.open("ab") as handle:
                        handle.write(b'{"interrupted":')
                    raise OSError("simulated manifest append failure")
                original_append(path, line)

            with patch.object(capture, "_append_line", side_effect=fault):
                with self.assertRaisesRegex(OSError, "simulated"):
                    capture.append_record(a, b, _record(2))
            self.assertEqual(a.read_bytes(), before_a)
            self.assertEqual(b.read_bytes(), before_b)
            self.assertTrue(capture.verify_capture_chain(a, b)["ok"])
            self.assertEqual(capture.append_record(a, b, _record(3))["seq"], 2)

    def test_incomplete_crash_pair_refuses_extension(self):
        with tempfile.TemporaryDirectory() as folder:
            a = Path(folder) / "captures.jsonl"
            b = Path(folder) / "manifest.jsonl"
            capture.append_record(a, b, _record(1))
            with a.open("ab") as handle:
                handle.write(capture.canonical_line(_record(2)) + b"\n")
            before_a, before_b = a.read_bytes(), b.read_bytes()
            with self.assertRaisesRegex(
                capture.StarterCaptureError,
                "CAPTURE_CHAIN_PREAPPEND_INVALID:RECORD_COUNT_MISMATCH",
            ):
                capture.append_record(a, b, _record(3))
            self.assertEqual((a.read_bytes(), b.read_bytes()), (before_a, before_b))

    def test_captured_file_tamper_refuses_extension(self):
        with tempfile.TemporaryDirectory() as folder:
            a = Path(folder) / "captures.jsonl"
            b = Path(folder) / "manifest.jsonl"
            capture.append_record(a, b, _record(1))
            a.write_bytes(a.read_bytes().replace(b"slot-1", b"slot-9"))
            with self.assertRaisesRegex(
                capture.StarterCaptureError,
                "CAPTURE_CHAIN_PREAPPEND_INVALID:CAPTURE_RECORD_HASH_MISMATCH",
            ):
                capture.append_record(a, b, _record(2))

    def test_unterminated_jsonl_pair_is_rejected_not_extended(self):
        with tempfile.TemporaryDirectory() as folder:
            a = Path(folder) / "captures.jsonl"
            b = Path(folder) / "manifest.jsonl"
            capture.append_record(a, b, _record(1))
            # Both JSON objects and their hashes still parse, but neither
            # JSONL file has the record delimiter required for an append.
            a.write_bytes(a.read_bytes()[:-1])
            b.write_bytes(b.read_bytes()[:-1])
            before = (a.read_bytes(), b.read_bytes())
            verdict = capture.verify_capture_chain(a, b)
            self.assertFalse(verdict["ok"])
            self.assertEqual(verdict["failure"]["reason"], "CAPTURE_LINE_UNTERMINATED")
            with self.assertRaisesRegex(
                capture.StarterCaptureError,
                "CAPTURE_CHAIN_PREAPPEND_INVALID:CAPTURE_LINE_UNTERMINATED",
            ):
                capture.append_record(a, b, _record(2))
            self.assertEqual((a.read_bytes(), b.read_bytes()), before)

    def test_manifest_metadata_tampering_refused_even_with_intact_digest(self):
        with tempfile.TemporaryDirectory() as folder:
            a = Path(folder) / "captures.jsonl"
            b = Path(folder) / "manifest.jsonl"
            capture.append_record(a, b, _record(1))
            entry = capture.read_manifest(b)[0]
            entry["game_pk"] = 999999  # digest and chain deliberately unchanged
            b.write_bytes(capture.canonical_line(entry) + b"\n")
            verdict = capture.verify_capture_chain(a, b)
            self.assertFalse(verdict["ok"])
            self.assertEqual(verdict["failure"]["reason"], "MANIFEST_METADATA_MISMATCH")
            with self.assertRaisesRegex(
                capture.StarterCaptureError,
                "CAPTURE_CHAIN_PREAPPEND_INVALID:MANIFEST_METADATA_MISMATCH",
            ):
                capture.append_record(a, b, _record(2))

    def test_same_file_for_capture_and_manifest_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            a = Path(folder) / "all.jsonl"
            with self.assertRaisesRegex(
                capture.StarterCaptureError, "CAPTURE_AND_MANIFEST_PATH_COLLIDE"
            ):
                capture.append_record(a, a, _record(1))
            self.assertFalse(a.exists())


if __name__ == "__main__":
    unittest.main()
