"""Boundary-interruption recovery battery for the journaled receipt recorder.

Acceptance requirement (integration ruling, Oct 14): interruption must be
tested at EACH durable-write boundary of one receipt append, not just the
known kill-9 point. Recovery must either verify a complete committed
receipt or fail closed with an explicit reason. No silent repair, no
skipped journal entry, no continued acceptance after detecting an orphan.

BOUNDARY MAP -- the durable steps of ONE append of receipt #2 onto a root
already holding committed receipt #1, read from the code under test
(``sportsedge/mlb_source.py`` @ the reconciled head):

``MLBSourceCapture._append_receipt_locked`` sequences four
``_durable_receipt_write`` calls (each one = descriptor open, write loop,
``os.fsync(fd)``, close, ``_fsync_dir(parent)``) plus two explicit
``_fsync_dir`` calls:

  DW1  _append_line_fsync(intent, BEGIN)      [mlb_source.py, try block]
         write BEGIN line / fsync #1 (file) / fsync #2 (directory)
  DW2  _durable_receipt_write(raw payload)    [append=False]
         write raw bytes  / fsync #3 (file) / fsync #4 (directory)
  X1   _fsync_dir(root)                        fsync #5
  DW3  _append_line_fsync(journal, entry)
         write journal line / fsync #6 (file) / fsync #7 (directory)
  X2   _fsync_dir(root)                        fsync #8
  DW4  _append_line_fsync(intent, COMMIT)
         write COMMIT line / fsync #9 (file) / fsync #10 (directory)

Boundaries B0..B11 are the death points between these steps; torn cases
T1..T4 die DURING a write call with partial bytes on disk. fsync-only
micro-boundaries (death after a write but before its fsync) are staged by
counting ``os.fsync`` calls: under process death, written-but-unfsynced
bytes survive (fsync bounds machine-crash loss, not process death), so
each micro-boundary's expected residue equals its write boundary's class
-- asserted individually below, not assumed.

WHY SUBPROCESS INJECTION: ``_append_receipt_locked`` rolls back on
``except BaseException``, so NO in-process exception can simulate process
death -- the rollback would run, write ABORT, and repair the pair. Every
deterministic case therefore runs in a child process that wraps the
module's own seams (``_durable_receipt_write`` / ``os.fsync``), writes a
marker naming the staged boundary, and dies with ``os._exit(9)`` at that
boundary -- no exception propagation, no rollback, no ABORT. Each test
additionally asserts the intent journal on disk contains NO ABORT line
for the interrupted append, proving the death bypassed the rollback
handler the way SIGKILL does. Two further cases (K1/K2) use real
SIGKILL: K1 reproduces the pair-window kill of the preserved
``kill9_repro.py``; K2 stages death after the journal line via a
sentinel file + sleep in the child, killed by the parent.

ORACLE (per boundary, exactly one outcome, asserted by NAME):
  (a) VERIFY -- the root verifies and the receipt set is EXACTLY the
      receipts committed before the interrupted append (B0), or before
      plus the interrupted one when its COMMIT is on disk (B10/B11);
      the interrupted append contributes nothing else, not even a
      partially-counted entry.
  (b) REFUSE -- verification fails closed with the specific named status
      the construction defines for that residue class:
        RECEIPT_RAW_ORPHAN_UNJOURNALED    (raw durable, journal line not)
        RECEIPT_INTENT_ORPHAN_UNCOMMITTED (BEGIN open; incl. journal
                                           line durable but COMMIT not)
        RECEIPT_JOURNAL_UNTERMINATED      (torn journal line)
        RECEIPT_INTENT_JOURNAL_UNTERMINATED (torn BEGIN / COMMIT line)
      Verifier check order (from ``verify_receipt_journal``): journal
      parse/chain -> orphan rule -> pending-intent rule; the expected
      status per case follows that order.
For every REFUSE case the battery additionally asserts a fresh recorder
refuses the damaged root BY THE SAME NAME at construction (the append
path's front door: ``__init__`` re-verifies, and ``_append_receipt_locked``
re-verifies under the lock before writing), and that the on-disk residue
is BYTE-IDENTICAL before and after the refused attempt -- nothing
silently repaired or extended.

Every child runs under a hard timeout; this suite can never hang.
"""
import os
import signal
import subprocess
import sys
import textwrap
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from sportsedge import mlb_source as ms

T0 = datetime(2026, 10, 13, 16, 0, tzinfo=timezone.utc)
LATER = T0 + timedelta(hours=1)
REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_URL = "https://x/api/v1/schedule"
SEED_RAW = b'{"seed":1}'
VICTIM_URL = "https://x/api/v1/game/4242/boxscore"
VICTIM_RAW = b'{"game":4242}'
NEXT_URL = "https://x/api/v1/game/5555/boxscore"
NEXT_RAW = b'{"game":5555}'

ORPHAN = "RECEIPT_RAW_ORPHAN_UNJOURNALED"
UNCOMMITTED = "RECEIPT_INTENT_ORPHAN_UNCOMMITTED"
JOURNAL_TORN = "RECEIPT_JOURNAL_UNTERMINATED"
INTENT_TORN = "RECEIPT_INTENT_JOURNAL_UNTERMINATED"


# ---------------------------------------------------------------------------
# Harness: seeding, snapshots, verification oracle
# ---------------------------------------------------------------------------

def _record(rec, *, url, raw, when=T0):
    """One receipt through the real recorder, clocks pinned as in the
    established receipt batteries (recorder clock + system anchor)."""
    rec.clock = lambda: when
    with patch.object(ms, "_trusted_now", lambda: when):
        return rec.record(url=url, raw=raw, fetch_started_at=when,
                          received_at=when + timedelta(seconds=1))


def _seed_root(base: Path) -> Path:
    """A root holding exactly one fully committed receipt (#1)."""
    root = base / "cap"
    root.mkdir(parents=True)
    rec = ms.MLBSourceCapture(root, clock=lambda: T0)
    _record(rec, url=SEED_URL, raw=SEED_RAW)
    entries = ms.verify_receipt_journal(root, verifier_now=LATER)
    assert [e["sequence"] for e in entries] == [1]
    return root


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes()
            for p in sorted(root.iterdir()) if p.is_file()}


def _verify_status(root: Path):
    """("verify", [sequences]) or ("refuse", status-string)."""
    try:
        entries = ms.verify_receipt_journal(root, verifier_now=LATER)
    except ms.MLBSourceError as exc:
        return "refuse", str(exc)
    return "verify", [e["sequence"] for e in entries]


def _assert_no_abort(root: Path) -> None:
    intent = root / ms.RECEIPT_INTENT_JOURNAL_NAME
    if intent.exists():
        assert b'"state":"ABORT"' not in intent.read_bytes(), \
            "an ABORT line exists: the rollback handler ran, so the " \
            "interruption did not simulate process death"


def _assert_refused_and_frozen(root: Path, status: str) -> None:
    """REFUSE oracle + no continued acceptance + residue byte-identical."""
    outcome, got = _verify_status(root)
    assert outcome == "refuse", f"expected refusal {status}, verified {got}"
    assert got == status, f"expected {status}, verifier said {got}"
    _assert_no_abort(root)
    before = _snapshot(root)
    with patch.object(ms, "_trusted_now", lambda: T0):
        with pytest.raises(ms.MLBSourceError) as excinfo:
            ms.MLBSourceCapture(root)  # fresh recorder refuses the root
    assert str(excinfo.value) == status, \
        f"fresh recorder refused with {excinfo.value}, expected {status}"
    assert _snapshot(root) == before, \
        "residue changed across a refused recorder attempt (silent repair)"


def _assert_verified_and_extensible(root: Path, sequences: list[int]) -> None:
    """VERIFY oracle: exactly the committed set, and the root still
    accepts the NEXT receipt (proving nothing was skipped or miscounted)."""
    outcome, got = _verify_status(root)
    assert outcome == "verify", f"expected verify {sequences}, refused {got}"
    assert got == sequences, f"expected sequences {sequences}, got {got}"
    _assert_no_abort(root)
    rec = ms.MLBSourceCapture(root, clock=lambda: T0)
    _record(rec, url=NEXT_URL, raw=NEXT_RAW)
    outcome, got = _verify_status(root)
    assert outcome == "verify"
    assert got == sequences + [sequences[-1] + 1]


# ---------------------------------------------------------------------------
# Deterministic boundary injection (subprocess, os._exit(9) at the seam)
# ---------------------------------------------------------------------------

_CHILD = textwrap.dedent(
    """
    import os, sys
    from datetime import datetime, timedelta, timezone
    from pathlib import Path
    from unittest.mock import patch
    from sportsedge import mlb_source as ms

    root, marker = Path(sys.argv[1]), Path(sys.argv[2])
    mode, param = sys.argv[3], int(sys.argv[4])
    T0 = datetime(2026, 10, 13, 16, 0, tzinfo=timezone.utc)

    real_dw = ms._durable_receipt_write
    real_fsync = os.fsync
    state = {"dw": 0, "fsync": 0}

    def die():
        marker.write_text(f"{mode}:{param}")
        os._exit(9)

    def dw_wrapper(path, data, *, append):
        state["dw"] += 1
        k = state["dw"]
        if mode == "before_dw" and k == param:
            die()
        if mode == "torn_dw" and k == param:
            # Partial bytes through the same descriptor discipline the
            # real helper uses, then death mid-write: a torn file.
            flags = (os.O_WRONLY | os.O_CREAT
                     | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_NONBLOCK", 0))
            flags |= os.O_APPEND if append else os.O_EXCL
            fd = os.open(path, flags, 0o600)
            try:
                os.write(fd, data[: max(1, len(data) // 2)])
                real_fsync(fd)
            finally:
                os.close(fd)
            die()
        result = real_dw(path, data, append=append)
        if mode == "after_dw" and k == param:
            die()
        return result

    def fsync_wrapper(fd):
        state["fsync"] += 1
        if mode == "before_fsync" and state["fsync"] == param:
            die()
        return real_fsync(fd)

    rec = ms.MLBSourceCapture(root, clock=lambda: T0)
    with patch.object(ms, "_trusted_now", lambda: T0):
        with patch.object(ms, "_durable_receipt_write", dw_wrapper):
            with patch.object(os, "fsync", fsync_wrapper):
                rec.record(url="https://x/api/v1/game/4242/boxscore",
                           raw=b'{"game":4242}',
                           fetch_started_at=T0,
                           received_at=T0 + timedelta(seconds=1))
    marker.write_text("COMPLETED_WITHOUT_DYING")
    """
)


def _run_injection(tmp_path: Path, mode: str, param: int) -> Path:
    """Seed a root, run the injection child against it, assert the child
    died at the staged boundary (marker + exit code 9), return the root."""
    case = tmp_path / f"case_{mode}_{param}"
    case.mkdir()
    root = _seed_root(case)
    marker = case / "marker.txt"
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD, str(root), str(marker), mode,
         str(param)],
        cwd=str(REPO_ROOT), env=env, capture_output=True, text=True,
        timeout=60)
    assert proc.returncode == 9, \
        f"child did not die by injection (rc={proc.returncode}): " \
        f"{proc.stdout} {proc.stderr}"
    assert marker.read_text() == f"{mode}:{param}", \
        "child died, but not at the staged boundary"
    return root


# (case id, injection mode, injection param, expected outcome)
# expected outcome: ("verify", [seqs]) or ("refuse", STATUS)
BOUNDARY_CASES = [
    # B0: death before the BEGIN write -- nothing of append #2 exists.
    ("B0_before_begin", "before_dw", 1, ("verify", [1])),
    # B1: BEGIN bytes written, death before the BEGIN file fsync.
    ("B1_begin_written", "before_fsync", 1, ("refuse", UNCOMMITTED)),
    # B2: BEGIN fsynced, death before the BEGIN directory fsync.
    ("B2_begin_fsynced", "before_fsync", 2, ("refuse", UNCOMMITTED)),
    # B3: BEGIN fully durable, death before the raw payload write.
    ("B3_begin_durable", "after_dw", 1, ("refuse", UNCOMMITTED)),
    # B4: raw bytes written, death before the raw fsync.
    ("B4_raw_written", "before_fsync", 3, ("refuse", ORPHAN)),
    # B5: raw fsynced, death before the raw directory fsync.
    ("B5_raw_fsynced", "before_fsync", 4, ("refuse", ORPHAN)),
    # B6: raw fully durable, death before the journal line write
    # (the explicit post-raw directory fsync leaves identical residue).
    ("B6_raw_durable", "after_dw", 2, ("refuse", ORPHAN)),
    # B7: journal line written, death before the journal fsync. The
    # journal entry IS on disk and chain-valid, but its COMMIT never
    # landed: it must NOT count as a verified receipt.
    ("B7_journal_written", "before_fsync", 6, ("refuse", UNCOMMITTED)),
    # B8: journal line fsynced, death before its directory fsync.
    ("B8_journal_fsynced", "before_fsync", 7, ("refuse", UNCOMMITTED)),
    # B9: journal line fully durable, death before the COMMIT write.
    ("B9_journal_durable", "after_dw", 3, ("refuse", UNCOMMITTED)),
    # B10: COMMIT bytes written, death before the COMMIT fsync. Process
    # death preserves written bytes: the receipt IS complete committed.
    ("B10_commit_written", "before_fsync", 9, ("verify", [1, 2])),
    # B11: COMMIT fully durable; death after the append's durable work,
    # before record() returns to its caller.
    ("B11_commit_durable", "after_dw", 4, ("verify", [1, 2])),
    # T1: torn BEGIN line (partial bytes in the intent journal).
    ("T1_torn_begin", "torn_dw", 1, ("refuse", INTENT_TORN)),
    # T2: torn raw payload (partial bytes, no journal reference).
    ("T2_torn_raw", "torn_dw", 2, ("refuse", ORPHAN)),
    # T3: torn journal line (partial line, no terminating newline).
    ("T3_torn_journal", "torn_dw", 3, ("refuse", JOURNAL_TORN)),
    # T4: torn COMMIT line (partial bytes in the intent journal).
    ("T4_torn_commit", "torn_dw", 4, ("refuse", INTENT_TORN)),
]


@pytest.mark.parametrize(
    "mode,param,outcome",
    [c[1:] for c in BOUNDARY_CASES],
    ids=[c[0] for c in BOUNDARY_CASES])
def test_interruption_at_each_durable_boundary(tmp_path, mode, param,
                                                 outcome):
    root = _run_injection(tmp_path, mode, param)
    kind, expected = outcome
    if kind == "verify":
        _assert_verified_and_extensible(root, expected)
    else:
        _assert_refused_and_frozen(root, expected)


# ---------------------------------------------------------------------------
# Process-level SIGKILL cases
# ---------------------------------------------------------------------------

_KILL_CHILD = textwrap.dedent(
    """
    import sys
    from datetime import datetime, timezone
    from pathlib import Path
    from sportsedge import mlb_source as ms

    root, ready = Path(sys.argv[1]), Path(sys.argv[2])
    rec = ms.MLBSourceCapture(root, clock=lambda: datetime.now(timezone.utc))
    raw = b"x" * (6 * 1024 * 1024)
    ready.touch()
    for n in range(30):
        start = datetime.now(timezone.utc)
        rec.record(url=f"https://x/api/v1/game/{5000 + n}/boxscore",
                   raw=raw + str(n).encode(),
                   fetch_started_at=start,
                   received_at=datetime.now(timezone.utc))
    """
)


def _raw_names(root: Path) -> list[str]:
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir()
                  if ms._RECEIPT_RAW_NAME_RE.match(p.name))


def _journal_line_count(root: Path) -> int:
    journal = root / ms.RECEIPT_JOURNAL_NAME
    return journal.read_bytes().count(b"\n") if journal.exists() else 0


def test_sigkill_in_pair_window_refuses_by_name(tmp_path):
    """K1: real SIGKILL while a raw payload is visible ahead of the
    journal (the preserved kill9_repro staging). The torn root must be
    refused by name, and no fresh recorder may append onto it."""
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
    status = None
    root = None
    for attempt in range(3):
        root = tmp_path / f"k1_{attempt}" / "cap"
        root.mkdir(parents=True)
        ready = root.parent / "ready"
        proc = subprocess.Popen(
            [sys.executable, "-c", _KILL_CHILD, str(root), str(ready)],
            cwd=str(REPO_ROOT), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.time() + 60
            while not ready.exists():
                assert time.time() < deadline, "writer did not start"
                time.sleep(0.005)
            torn_seen = False
            deadline = time.time() + 60
            while time.time() < deadline and proc.poll() is None:
                journaled = _journal_line_count(root)
                if any(int(name[:4]) > journaled
                       for name in _raw_names(root)):
                    torn_seen = True
                    break
                time.sleep(0.0005)
            if proc.poll() is None:
                proc.send_signal(signal.SIGKILL)
            proc.wait(timeout=30)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=30)
        if not torn_seen:
            continue  # window never caught this attempt; retry fresh
        try:
            ms.verify_receipt_journal(
                root, verifier_now=datetime.now(timezone.utc)
                + timedelta(hours=1))
        except ms.MLBSourceError as exc:
            status = str(exc)
        break
    assert status is not None, \
        "SIGKILL in the pair window was not refused (or window uncaught)"
    assert "ORPHAN" in status or "UNTERMINATED" in status, \
        f"torn root refused with an unexpected status: {status}"
    _assert_no_abort(root)
    before = _snapshot(root)
    with pytest.raises(ms.MLBSourceError) as excinfo:
        ms.MLBSourceCapture(root)
    assert str(excinfo.value) == status
    assert _snapshot(root) == before


_SENTINEL_CHILD = textwrap.dedent(
    """
    import sys, time
    from datetime import datetime, timedelta, timezone
    from pathlib import Path
    from unittest.mock import patch
    from sportsedge import mlb_source as ms

    root, sentinel = Path(sys.argv[1]), Path(sys.argv[2])
    T0 = datetime(2026, 10, 13, 16, 0, tzinfo=timezone.utc)

    real_dw = ms._durable_receipt_write
    state = {"dw": 0}

    def dw_wrapper(path, data, *, append):
        state["dw"] += 1
        result = real_dw(path, data, append=append)
        if state["dw"] == 3:
            # Journal line for receipt #2 is durable; COMMIT has not
            # been attempted. Hold the window open for the parent's
            # SIGKILL.
            sentinel.touch()
            time.sleep(60)
        return result

    rec = ms.MLBSourceCapture(root, clock=lambda: T0)
    rec.clock = lambda: T0
    with patch.object(ms, "_trusted_now", lambda: T0):
        rec.record(url="https://x/api/v1/schedule", raw=b'{"seed":1}',
                   fetch_started_at=T0,
                   received_at=T0 + timedelta(seconds=1))
    state["dw"] = 0
    with patch.object(ms, "_trusted_now", lambda: T0):
        with patch.object(ms, "_durable_receipt_write", dw_wrapper):
            rec.record(url="https://x/api/v1/game/4242/boxscore",
                       raw=b'{"game":4242}',
                       fetch_started_at=T0,
                       received_at=T0 + timedelta(seconds=1))
    """
)


def test_sigkill_after_journal_line_before_commit(tmp_path):
    """K2: real SIGKILL staged after the journal line is durable but
    before COMMIT is attempted (sentinel + sleep in the child). The
    journal entry must NOT count as verified: refusal by
    RECEIPT_INTENT_ORPHAN_UNCOMMITTED, and the root stays frozen."""
    root = tmp_path / "k2" / "cap"
    root.mkdir(parents=True)
    sentinel = root.parent / "sentinel"
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
    proc = subprocess.Popen(
        [sys.executable, "-c", _SENTINEL_CHILD, str(root), str(sentinel)],
        cwd=str(REPO_ROOT), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.time() + 60
        while not sentinel.exists():
            assert time.time() < deadline, \
                "child never reached the post-journal-line window"
            assert proc.poll() is None, "child exited before the window"
            time.sleep(0.005)
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=30)
    # The journal holds both entries on disk; only #1 is committed.
    assert _journal_line_count(root) == 2
    _assert_refused_and_frozen(root, UNCOMMITTED)
