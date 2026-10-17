"""Adversarial tests: crash-safe, cross-process write-ahead starter capture.

Offline only; fake clocks drive capture_snapshot. No timestamp is created by
the commit layer. Research-only: nothing here authorizes pricing or betting.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sportsedge import mlb_source
from sportsedge.sports.mlb import starter_capture as sc
from tests.test_mlb_starter_loader_raw_20261013 import (
    AS_OF, NOW, PITCH_S, PK, T_CAP, Harness, _game, _payload,
)


def _snap(h, n=0):
    g = _game()
    g["venue"] = {"id": n}  # distinct raw bytes per call
    raw = json.dumps(_payload(g)).encode()
    rec = sc.capture_snapshot(h.plan, "T-30M", fetcher=lambda url: raw, clock=lambda: T_CAP)
    return rec, raw


def _commit(h, n=0):
    rec, raw = _snap(h, n)
    return sc.commit_capture_atomic(h.cap, h.man, h.raw, rec, raw, verifier_now=NOW)


def _verify(h):
    return sc.verify_capture_store(h.cap, h.man, h.raw, verifier_now=NOW)


def _recover(h):
    return sc.recover_capture_store(h.cap, h.man, h.raw, verifier_now=NOW)


def _writer(root, wid, n):
    h = Harness(Path(root))
    for i in range(n):
        _commit(h, wid * 1000 + i)


def _killer(root, mode, nth):
    h = Harness(Path(root))
    count = {"n": 0}
    real_fsync = os.fsync

    def die_fsync(fd):
        count["n"] += 1
        if count["n"] == nth:
            os._exit(9)
        return real_fsync(fd)

    if mode == "replace":
        os.replace = lambda *a, **k: os._exit(9)
    else:
        os.fsync = die_fsync
    _commit(h, 7)
    os._exit(0)


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.h = Harness(self.root)
        self.q = self.h.raw.with_name("raw.quarantine")

    def tearDown(self):
        self._tmp.cleanup()

    def reasons(self):
        if not self.q.exists():
            return []
        return sorted(json.loads(p.read_bytes())["reason"] for p in self.q.glob("*.reason.json"))


class HappyPath(Base):
    def test_commit_verifies_and_links_raw(self):
        out = _commit(self.h)
        self.assertEqual(out["seq"], 1)
        v = _verify(self.h)
        self.assertTrue(v["ok"], v)
        self.assertEqual(v["raw_verified"], 1)
        self.assertEqual(out["record"]["raw_sha256"], out["record"]["response_sha256"])

    def test_commit_never_adds_timestamps(self):
        rec, raw = _snap(self.h)
        out = sc.commit_capture_atomic(self.h.cap, self.h.man, self.h.raw, rec, raw, verifier_now=NOW)
        added = set(out["record"]) - set(rec)
        self.assertEqual(added, {"raw_store_file", "raw_sha256", "raw_byte_length", "raw_store_kind"})
        for line in (self.h.man.with_name("manifest.jsonl.intent.jsonl")).read_bytes().splitlines():
            obj = json.loads(line)
            self.assertFalse([k for k in obj if k.endswith("_utc") or k.endswith("_at")])

    def test_bad_clock_rejected_before_any_write(self):
        rec, raw = _snap(self.h)
        rec["captured_at_utc"] = "2000-01-01T00:00:00Z"
        with self.assertRaises(sc.StarterCaptureError):
            sc.commit_capture_atomic(self.h.cap, self.h.man, self.h.raw, rec, raw, verifier_now=NOW)
        self.assertFalse(self.h.cap.exists())
        self.assertFalse(self.h.raw.exists())

    def test_digest_divergence_rejected(self):
        rec, raw = _snap(self.h)
        with self.assertRaises(sc.StarterCaptureError):
            sc.commit_capture_atomic(self.h.cap, self.h.man, self.h.raw, rec, raw + b" ", verifier_now=NOW)

    def test_loader_accepts_atomic_store(self):
        # Single record via the atomic path, with a #2166 receipt for its bytes.
        rec, raw = _snap(self.h, 3)
        with mock.patch.object(mlb_source, "_trusted_now", return_value=T_CAP):
            mlb_source.MLBSourceCapture(self.h.rcpt, clock=lambda: T_CAP).record(
                url=rec["source_url"], raw=raw, fetch_started_at=T_CAP, received_at=T_CAP)
        sc.commit_capture_atomic(self.h.cap, self.h.man, self.h.raw, rec, raw, verifier_now=NOW)
        out = self.h.load()
        self.assertEqual(out["binding_status"], "RESEARCH_BOUND", out)
        self.assertEqual(out["max_action"], "WATCH")
        self.assertFalse(out["pricing_authorized"])
        self.assertFalse(out["betting_authorized"])


class CrashInjection(Base):
    """fsync call order inside a commit on a clean store:
    1 intent BEGIN, 2 raw temp, 3 raw dir, 4 capture, 5 manifest, 6 COMMIT."""

    def _crash_at_fsync(self, nth):
        _commit(self.h, 1)  # pre-existing good record
        real = os.fsync
        c = {"n": 0}

        def boom(fd):
            c["n"] += 1
            if c["n"] == nth:
                raise OSError("injected fsync failure")
            return real(fd)

        rec, raw = _snap(self.h, 2)
        with mock.patch("os.fsync", boom):
            with self.assertRaises(OSError):
                sc.commit_capture_atomic(self.h.cap, self.h.man, self.h.raw, rec, raw, verifier_now=NOW)
        return rec

    def test_each_fsync_step(self):
        expect = {1: ("ABORT_RAW_MISSING", 1), 2: ("ABORT_RAW_MISSING", 1),
                  3: ("ROLL_FORWARD_FULL", 2), 4: ("ROLL_FORWARD_TAIL", 2),
                  5: ("ROLL_FORWARD_TAIL", 2)}
        for nth, (state, n) in expect.items():
            with self.subTest(nth=nth):
                self.tearDown(); self.setUp()
                self._crash_at_fsync(nth)
                if nth < 6:
                    self.assertFalse(_verify(self.h)["ok"])
                out = _recover(self.h)
                self.assertIn(state, out["actions"])
                v = _verify(self.h)
                self.assertTrue(v["ok"], v)
                self.assertEqual(v["records_checked"], n)
                if nth == 2:
                    self.assertIn("RAW_TEMP_WITHOUT_RENAME", self.reasons())
                _commit(self.h, 9)  # store keeps working after recovery
                self.assertTrue(_verify(self.h)["ok"])

    def test_commit_marker_fsync_failure_is_harmless(self):
        self._crash_at_fsync(6)
        # COMMIT line was written (fsync raised after write) -> already closed.
        self.assertTrue(_verify(self.h)["ok"])

    def test_os_replace_failure_aborts_and_quarantines_temp(self):
        _commit(self.h, 1)
        rec, raw = _snap(self.h, 2)
        with mock.patch("os.replace", side_effect=OSError("injected")):
            with self.assertRaises(OSError):
                sc.commit_capture_atomic(self.h.cap, self.h.man, self.h.raw, rec, raw, verifier_now=NOW)
        self.assertEqual(_verify(self.h)["failure"]["reason"], "INTENT_UNCOMMITTED")
        out = _recover(self.h)
        self.assertIn("ABORT_RAW_MISSING", out["actions"])
        self.assertIn("RAW_TEMP_WITHOUT_RENAME", self.reasons())
        self.assertTrue(_verify(self.h)["ok"])

    def test_torn_capture_line_mid_write_rolls_forward(self):
        _commit(self.h, 1)
        real = sc._append_line

        def half(path, line):
            if Path(path).name == "capture.jsonl":
                with Path(path).open("ab") as f:
                    f.write(line[: len(line) // 2])
                raise OSError("killed mid-write")
            return real(path, line)

        rec, raw = _snap(self.h, 2)
        with mock.patch.object(sc, "_append_line", half):
            with self.assertRaises(OSError):
                sc.commit_capture_atomic(self.h.cap, self.h.man, self.h.raw, rec, raw, verifier_now=NOW)
        out = _recover(self.h)
        self.assertIn("ROLL_FORWARD_FULL", out["actions"])
        self.assertIn("TORN_TERMINAL_LINE:capture.jsonl", self.reasons())
        v = _verify(self.h)
        self.assertTrue(v["ok"], v)
        self.assertEqual(v["records_checked"], 2)

    def test_subprocess_killed_at_each_fsync(self):
        ctx = mp.get_context("fork")
        for nth in range(1, 7):
            with self.subTest(nth=nth):
                self.tearDown(); self.setUp()
                _commit(self.h, 1)
                p = ctx.Process(target=_killer, args=(str(self.root), "fsync", nth))
                p.start(); p.join(30)
                self.assertEqual(p.exitcode, 9)
                _recover(self.h)
                v = _verify(self.h)
                self.assertTrue(v["ok"], v)
                self.assertIn(v["records_checked"], (1, 2))
                self.assertEqual(v["records_checked"], 1 if nth <= 2 else 2)

    def test_subprocess_killed_at_replace(self):
        _commit(self.h, 1)
        p = mp.get_context("fork").Process(target=_killer, args=(str(self.root), "replace", 0))
        p.start(); p.join(30)
        self.assertEqual(p.exitcode, 9)
        self.assertFalse(_verify(self.h)["ok"])
        _recover(self.h)
        self.assertTrue(_verify(self.h)["ok"])
        self.assertIn("RAW_TEMP_WITHOUT_RENAME", self.reasons())

    def test_next_commit_auto_recovers(self):
        _commit(self.h, 1)
        with mock.patch("os.replace", side_effect=OSError("x")):
            with self.assertRaises(OSError):
                _commit(self.h, 2)
        _commit(self.h, 3)
        v = _verify(self.h)
        self.assertTrue(v["ok"], v)
        self.assertEqual(v["records_checked"], 2)


class FailClosed(Base):
    def test_truncated_last_line_without_intent_fails_closed(self):
        _commit(self.h, 1)
        with self.h.cap.open("ab") as f:
            f.write(b'{"record_type":"SNAP')
        self.assertEqual(_verify(self.h)["failure"]["reason"], "CAPTURE_LINE_UNTERMINATED")
        with self.assertRaises(sc.StarterCaptureError) as cm:
            _recover(self.h)
        self.assertIn("CAPTURE_LINE_UNTERMINATED", str(cm.exception))
        with self.assertRaises(sc.StarterCaptureError):
            _commit(self.h, 2)
        self.assertTrue(self.h.cap.read_bytes().endswith(b"SNAP"))  # evidence untouched

    def test_truncated_manifest_line_without_intent_fails_closed(self):
        _commit(self.h, 1)
        with self.h.man.open("ab") as f:
            f.write(b'{"seq":2')
        with self.assertRaises(sc.StarterCaptureError):
            _recover(self.h)

    def test_torn_intent_line_is_quarantined(self):
        _commit(self.h, 1)
        ip = self.h.man.with_name("manifest.jsonl.intent.jsonl")
        with ip.open("ab") as f:
            f.write(b'{"schema":"mlb_starter_capture_inte')
        self.assertEqual(_verify(self.h)["failure"]["reason"], "INTENT_LINE_UNTERMINATED")
        out = _recover(self.h)
        self.assertIn("QUARANTINED_TORN_INTENT_LINE", out["actions"])
        self.assertTrue(_verify(self.h)["ok"])

    def test_orphan_blob_quarantined_with_reason(self):
        _commit(self.h, 1)
        orphan = self.h.raw / ("a" * 64 + ".json")
        orphan.write_bytes(b'{"orphan":true}')
        self.assertEqual(_verify(self.h)["failure"]["reason"], "RAW_ORPHAN_BLOB")
        out = _recover(self.h)
        self.assertTrue(any(a.startswith("QUARANTINED_ORPHAN") for a in out["actions"]))
        self.assertFalse(orphan.exists())
        self.assertIn("RAW_ORPHAN_BLOB_UNREFERENCED", self.reasons())
        kept = [p.read_bytes() for p in self.q.glob("*.bin")]
        self.assertIn(b'{"orphan":true}', kept)
        self.assertTrue(_verify(self.h)["ok"])

    def test_capture_line_without_intent_fails_closed(self):
        _commit(self.h, 1)
        rec, _ = _snap(self.h, 2)
        with self.h.cap.open("ab") as f:
            f.write(sc.canonical_line(rec) + b"\n")
        with self.assertRaises(sc.StarterCaptureError):
            _recover(self.h)

    def test_tampered_intent_record_fails_closed(self):
        _commit(self.h, 1)
        with mock.patch("os.replace", side_effect=OSError("x")):
            with self.assertRaises(OSError):
                _commit(self.h, 2)
        ip = self.h.man.with_name("manifest.jsonl.intent.jsonl")
        lines = ip.read_bytes().splitlines()
        obj = json.loads(lines[-1]); obj["record_line"] = obj["record_line"].replace("T-30M", "T-10M")
        lines[-1] = sc.canonical_line(obj)
        ip.write_bytes(b"\n".join(lines) + b"\n")
        with self.assertRaises(sc.StarterCaptureError) as cm:
            _recover(self.h)
        self.assertIn("INTENT_RECORD_DIGEST_MISMATCH", str(cm.exception))

    def test_raw_deleted_after_capture_line_fails_closed(self):
        _commit(self.h, 1)
        real = sc._append_line

        def stop(path, line):
            if Path(path).name == "manifest.jsonl":
                raise OSError("crash")
            return real(path, line)

        rec, raw = _snap(self.h, 2)
        with mock.patch.object(sc, "_append_line", stop):
            with self.assertRaises(OSError):
                sc.commit_capture_atomic(self.h.cap, self.h.man, self.h.raw, rec, raw, verifier_now=NOW)
        (self.h.raw / f"{rec['response_sha256']}.json").unlink()
        with self.assertRaises(sc.StarterCaptureError) as cm:
            _recover(self.h)
        self.assertIn("INTENT_STATE_UNEXPLAINED", str(cm.exception))


class Concurrency(Base):
    def test_multiprocess_writers(self):
        ctx = mp.get_context("fork")
        procs = [ctx.Process(target=_writer, args=(str(self.root), w, 5)) for w in range(4)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(60)
            self.assertEqual(p.exitcode, 0)
        v = _verify(self.h)
        self.assertTrue(v["ok"], v)
        self.assertEqual(v["records_checked"], 20)
        self.assertEqual(v["raw_verified"], 20)
        seqs = [json.loads(l)["seq"] for l in self.h.man.read_bytes().splitlines()]
        self.assertEqual(seqs, list(range(1, 21)))

    def test_writers_with_one_killed(self):
        ctx = mp.get_context("fork")
        procs = [ctx.Process(target=_writer, args=(str(self.root), w, 4)) for w in range(3)]
        killer = ctx.Process(target=_killer, args=(str(self.root), "fsync", 4))
        for p in procs + [killer]:
            p.start()
        for p in procs + [killer]:
            p.join(60)
        self.assertEqual(killer.exitcode, 9)
        _recover(self.h)
        v = _verify(self.h)
        self.assertTrue(v["ok"], v)
        self.assertIn(v["records_checked"], (12, 13))


if __name__ == "__main__":
    unittest.main()
