"""#2166 limitation closure: cross-process-safe paired writes + external anchor.

PART A hostiles target the base tree's two write-side weaknesses:
  * the receipt recorder kept sequence/chain state in memory (loaded once at
    construction) and appended with flush() only -- no lock, no fsync -- so
    two writer processes at one root fork the hash chain, and a crash between
    the raw-payload write and the journal append leaves a torn pair behind;
  * the journal verifier silently ignored raw payload files that no journal
    entry referenced, so a torn pair's surviving half was accepted as-is.

The fix under test: pair appends serialized under a stable POSIX flock, journal
state re-derived from disk under the lock, write+fsync per file then an fsync
of the directory, and a verifier rule that an unjournaled raw payload file is a
refused torn tail (RECEIPT_RAW_ORPHAN_UNJOURNALED), never repaired or extended.

The truncated-final-line case already failed closed on the base tree
(RECEIPT_JOURNAL_UNTERMINATED); it is kept here as a regression guard.

PART B tests cover the dark external-anchor module: preparation and
verification are pure/local, publication refuses while ANCHORING_ENABLED is
False, and a fake publisher exercises the enabled path. No network, no real
publication. Part B is additive: on the base tree the module does not exist.
"""
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from sportsedge import mlb_source as ms

T0 = datetime(2026, 10, 13, 16, 0, tzinfo=timezone.utc)
URL = "https://x/api/v1/schedule"
REPO_ROOT = Path(ms.__file__).resolve().parent.parent
RAW_NAME_RE = re.compile(r"^\d{4,}_.*_[0-9a-f]{64}\.json$")


def _record_at(rec, *, url=URL, raw=b"{}", when=T0):
    """Record one receipt with the trusted clock pinned at ``when``."""
    rec.clock = lambda: when  # the recorder-clock assertion rides the fetch start
    with patch.object(ms, "_trusted_now", lambda: when):
        return rec.record(url=url, raw=raw, fetch_started_at=when,
                          received_at=when + timedelta(seconds=1))


def _raw_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(p for p in root.iterdir() if RAW_NAME_RE.match(p.name))


# --------------------------------------------------------------------------
# PART A -- paired writes
# --------------------------------------------------------------------------

def test_two_instances_constructed_together_do_not_fork_the_chain(tmp_path):
    """Both recorders load the same empty state at construction (the base
    tree's fork condition). Interleaved appends must still serialize."""
    a = ms.MLBSourceCapture(tmp_path, clock=lambda: T0)
    b = ms.MLBSourceCapture(tmp_path, clock=lambda: T0)
    for i in range(3):
        _record_at(a, raw=json.dumps({"w": "a", "i": i}).encode(),
                   when=T0 + timedelta(seconds=10 * i))
        _record_at(b, raw=json.dumps({"w": "b", "i": i}).encode(),
                   when=T0 + timedelta(seconds=10 * i + 5))
    entries = ms.verify_receipt_journal(tmp_path, verifier_now=T0 + timedelta(hours=1))
    assert [e["sequence"] for e in entries] == [1, 2, 3, 4, 5, 6]
    assert len(_raw_files(tmp_path)) == 6


def test_orphaned_raw_payload_is_a_refused_torn_tail(tmp_path):
    rec = ms.MLBSourceCapture(tmp_path, clock=lambda: T0)
    _record_at(rec)
    ghost = tmp_path / ("0002_mlb_statsapi_schedule_" + "ab" * 32 + ".json")
    ghost.write_bytes(b"{}")
    with pytest.raises(ms.MLBSourceError, match="RECEIPT_RAW_ORPHAN_UNJOURNALED"):
        ms.verify_receipt_journal(tmp_path, verifier_now=T0 + timedelta(hours=1))
    with pytest.raises(ms.MLBSourceError, match="RECEIPT_RAW_ORPHAN_UNJOURNALED"):
        ms.MLBSourceCapture(tmp_path)  # a restarted recorder refuses the root too


def test_orphaned_raw_without_any_journal_is_refused(tmp_path):
    ghost = tmp_path / ("0001_mlb_statsapi_schedule_" + "cd" * 32 + ".json")
    ghost.write_bytes(b"{}")
    with pytest.raises(ms.MLBSourceError, match="RECEIPT_RAW_ORPHAN_UNJOURNALED"):
        ms.verify_receipt_journal(tmp_path, verifier_now=T0 + timedelta(hours=1))


def test_truncated_final_journal_line_is_refused_regression_guard(tmp_path):
    rec = ms.MLBSourceCapture(tmp_path, clock=lambda: T0)
    _record_at(rec)
    with open(tmp_path / ms.RECEIPT_JOURNAL_NAME, "ab") as fh:
        fh.write(b'{"sequence":2,"sour')  # torn tail: partial line, no newline
    with pytest.raises(ms.MLBSourceError, match="RECEIPT_JOURNAL_UNTERMINATED"):
        ms.verify_receipt_journal(tmp_path, verifier_now=T0 + timedelta(hours=1))


_CHILD_BARRIER_WRITER = r"""
import json, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from sportsedge import mlb_source as ms

root, barrier, idx, count = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
def wait_for(name, timeout=60.0):
    deadline = time.time() + timeout
    while not (barrier / name).exists():
        if time.time() > deadline:
            sys.exit(2)
        time.sleep(0.01)

wait_for("go1")
rec = ms.MLBSourceCapture(root, clock=lambda: datetime.now(timezone.utc))
(barrier / f"ready_{idx}").touch()
wait_for("go2")
for n in range(count):
    start = datetime.now(timezone.utc)
    rec.record(url=f"https://x/api/v1/game/{1000 + idx * 100 + n}/boxscore",
               raw=json.dumps({"child": idx, "n": n}).encode(),
               fetch_started_at=start, received_at=datetime.now(timezone.utc))
"""


def test_concurrent_writer_processes_never_interleave_or_fork(tmp_path):
    root, barrier = tmp_path / "cap", tmp_path / "barrier"
    root.mkdir(); barrier.mkdir()
    children, per_child = 3, 8
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
    procs = [subprocess.Popen([sys.executable, "-c", _CHILD_BARRIER_WRITER,
                               str(root), str(barrier), str(i), str(per_child)],
                              env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True)
             for i in range(children)]
    try:
        (barrier / "go1").touch()
        deadline = time.time() + 60
        while not all((barrier / f"ready_{i}").exists() for i in range(children)):
            assert time.time() < deadline, "writer children did not construct in time"
            time.sleep(0.01)
        (barrier / "go2").touch()
        for proc in procs:
            _, err = proc.communicate(timeout=120)
            assert proc.returncode == 0, f"writer child failed: {err}"
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.kill()
    entries = ms.verify_receipt_journal(root, verifier_now=datetime.now(timezone.utc) + timedelta(hours=1))
    total = children * per_child
    assert [e["sequence"] for e in entries] == list(range(1, total + 1))
    assert len(_raw_files(root)) == total


_CHILD_LOOP_WRITER = r"""
import json, sys
from datetime import datetime, timezone
from pathlib import Path
from sportsedge import mlb_source as ms

root, ready, count, size = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
rec = ms.MLBSourceCapture(root, clock=lambda: datetime.now(timezone.utc))
raw = b"x" * size
ready.touch()
for n in range(count):
    start = datetime.now(timezone.utc)
    rec.record(url=f"https://x/api/v1/game/{5000 + n}/boxscore", raw=raw + str(n).encode(),
               fetch_started_at=start, received_at=datetime.now(timezone.utc))
"""


def _journal_line_count(root: Path) -> int:
    journal = root / ms.RECEIPT_JOURNAL_NAME
    return journal.read_bytes().count(b"\n") if journal.exists() else 0


def test_kill_9_mid_pair_leaves_complete_pairs_or_refused_torn_tail(tmp_path):
    """Kill a writer while a pair is half-written. The surviving state must
    verify as complete pairs only, or be refused as a torn tail -- a partial
    pair must never be silently accepted."""
    caught_torn_window = False
    for round_no in range(3):
        root = tmp_path / f"cap{round_no}"
        root.mkdir()
        ready = tmp_path / f"ready{round_no}"
        env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
        proc = subprocess.Popen([sys.executable, "-c", _CHILD_LOOP_WRITER,
                                 str(root), str(ready), "30", str(6 * 1024 * 1024)],
                                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True)
        try:
            deadline = time.time() + 60
            while not ready.exists():
                assert time.time() < deadline, "loop writer did not start"
                time.sleep(0.005)
            torn_seen = False
            deadline = time.time() + 30
            while time.time() < deadline and proc.poll() is None:
                journaled = _journal_line_count(root)
                if any(int(p.name[:4]) > journaled for p in _raw_files(root)):
                    torn_seen = True
                    break
                time.sleep(0.0005)
            if proc.poll() is None:
                proc.send_signal(signal.SIGKILL)
            proc.wait(timeout=30)
            caught_torn_window = caught_torn_window or torn_seen
            if torn_seen:
                # The kill landed inside the pair window: refusal is mandatory.
                with pytest.raises(ms.MLBSourceError, match="ORPHAN|UNTERMINATED"):
                    ms.verify_receipt_journal(root, verifier_now=datetime.now(timezone.utc) + timedelta(hours=1))
            else:
                entries = ms.verify_receipt_journal(
                    root, verifier_now=datetime.now(timezone.utc) + timedelta(hours=1))
                assert len(entries) == _journal_line_count(root)
                assert len(_raw_files(root)) == len(entries)
        finally:
            if proc.poll() is None:
                proc.kill()
    assert caught_torn_window, "kill never landed inside a pair window in 3 rounds; test inconclusive"


# --------------------------------------------------------------------------
# PART B -- external anchor (dark, disabled by default)
# --------------------------------------------------------------------------

def _anchor_module():
    from sportsedge import mlb_receipt_anchor as anchor
    return anchor


class _FakePublisher:
    def __init__(self):
        self.published: list[dict] = []

    def publish(self, payload):
        self.published.append(payload)
        return {"published_at_utc": "2026-10-13T17:05:00+00:00",
                "location": "fake://records-branch/mlb_receipt_anchors/anchor.json",
                "anchor_id": payload["anchor_id"]}


def _seed_journal(root: Path, receipts: int = 2):
    rec = ms.MLBSourceCapture(root, clock=lambda: T0)
    for i in range(receipts):
        _record_at(rec, raw=json.dumps({"i": i}).encode(), when=T0 + timedelta(seconds=10 * i))
    return rec


def test_anchor_publication_refused_while_disabled_by_default(tmp_path):
    anchor = _anchor_module()
    assert anchor.ANCHORING_ENABLED is False
    _seed_journal(tmp_path)
    with pytest.raises(ms.MLBSourceError, match="RECEIPT_ANCHORING_DISABLED"):
        anchor.publish_receipt_anchor(tmp_path, _FakePublisher(),
                                      verifier_now=T0 + timedelta(hours=1))


def test_anchor_prepare_publish_verify_with_fake_publisher(tmp_path, monkeypatch):
    anchor = _anchor_module()
    _seed_journal(tmp_path)
    payload = anchor.prepare_receipt_anchor(tmp_path, verifier_now=T0 + timedelta(hours=1))
    assert payload["anchor_claim"] == "EXISTENCE_BY_GITHUB_PUBLICATION_RECEIPT"
    assert payload["anchored"] is False and payload["external_time_anchor"] is False
    assert payload["journal_last_sequence"] == 2 and payload["journal_entry_count"] == 2
    assert "NOT a cryptographic" in " ".join(payload["honest_limits"])
    monkeypatch.setattr(anchor, "ANCHORING_ENABLED", True)
    fake = _FakePublisher()
    published = anchor.publish_receipt_anchor(tmp_path, fake, verifier_now=T0 + timedelta(hours=1))
    assert fake.published and fake.published[0]["anchor_id"] == payload["anchor_id"]
    assert published["anchored"] is True and published["external_time_anchor"] is True
    result = anchor.verify_receipt_anchor(tmp_path, published, verifier_now=T0 + timedelta(hours=1))
    assert result["anchor_status"] == "MATCHES_LOCAL_JOURNAL"


def test_absent_anchor_is_unanchored_not_an_error(tmp_path):
    anchor = _anchor_module()
    _seed_journal(tmp_path)
    result = anchor.verify_receipt_anchor(tmp_path, None, verifier_now=T0 + timedelta(hours=1))
    assert result["anchor_status"] == "UNANCHORED" and result["external_time_anchor"] is False
    assert len(ms.verify_receipt_journal(tmp_path, verifier_now=T0 + timedelta(hours=1))) == 2


def test_anchor_mismatch_after_journal_extends(tmp_path):
    anchor = _anchor_module()
    rec = _seed_journal(tmp_path)
    payload = anchor.prepare_receipt_anchor(tmp_path, verifier_now=T0 + timedelta(hours=1))
    _record_at(rec, raw=b'{"i":99}', when=T0 + timedelta(seconds=60))
    with pytest.raises(ms.MLBSourceError, match="RECEIPT_ANCHOR_MISMATCH"):
        anchor.verify_receipt_anchor(tmp_path, payload, verifier_now=T0 + timedelta(hours=1))


def test_anchor_prepare_fails_closed_on_tampered_journal(tmp_path):
    anchor = _anchor_module()
    _seed_journal(tmp_path)
    journal = tmp_path / ms.RECEIPT_JOURNAL_NAME
    journal.write_bytes(journal.read_bytes()[:-1])  # torn tail
    with pytest.raises(ms.MLBSourceError):
        anchor.prepare_receipt_anchor(tmp_path, verifier_now=T0 + timedelta(hours=1))
    with pytest.raises(ms.MLBSourceError, match="RECEIPT_ANCHOR_NO_ENTRIES"):
        anchor.prepare_receipt_anchor(tmp_path / "empty", verifier_now=T0 + timedelta(hours=1))
