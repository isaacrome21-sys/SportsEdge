"""Verifier-durability battery for the B10 recovery sync (Oct 16).

B10 (owner exact-head audit of composition 489768f64, Oct 14): the
writer's pre-COMMIT fsync sequence has no missing step, but a COMMIT
whose bytes were written while its fsync never completed survives
process death in the page cache, and ``verify_receipt_journal`` accepted
it with no recovery sync -- acceptance after PROCESS death, which
proves nothing about durability across MACHINE power loss. From the
bytes alone the verifier cannot tell whether the writer's fsync
finished: the receipt's durability is indeterminate at read time.

The fix (``_sync_verified_receipt_commit``): once every structural
check passes, the verifier completes the durability chain itself --
fsync of the receipt journal, the intent journal and the root
directory -- and only then certifies. A sync failure refuses the root
by name (RECEIPT_RECOVERY_SYNC_FAILED). This battery pins:

DISCRIMINATORS (fail on the unmodified module, pass with the fix):
  * B10 residue + fsync failure during verify -> recovery-sync refusal,
    never acceptance.
  * B11 residue and an untouched committed root behave the same:
    acceptance is never sync-free once an intent journal exists.
  * Acceptance performs the chain's fsyncs (>= 3: journal, intent,
    directory), observed by tracking -- not assumed.

ORDERING PINS (pass before and after; the fix must not move them):
  * Structural refusals precede the sync: UNCOMMITTED / ORPHAN /
    UNTERMINATED residues keep their names even with fsync sabotaged.
  * Duplicate BEGIN, duplicate COMMIT and unpaired COMMIT keep their
    intent-integrity names.
  * A hostile intent path is refused by the structural reader's name,
    not the sync's.

POSTURE PINS (pass before and after):
  * Verification never rewrites bytes: a recovered root is
    byte-identical before and after acceptance, verifies twice, and
    still extends.
  * A legacy journal-only root (no intent journal) verifies with zero
    fsync calls: recovery sync grants no authority and does not engage
    where no COMMIT durability is in question.

Residues are staged with the boundary battery's discipline: a child
process wraps the module's own seams, dies with os._exit(9) at the
staged boundary (no rollback, no ABORT), and the parent asserts the
marker. fsync counting in the child starts at the append's first
durable write -- the verifier's recovery syncs of the PRIOR root are
not boundaries of the append under test.
"""
import os
import subprocess
import sys
import textwrap
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

ORPHAN = "RECEIPT_RAW_ORPHAN_UNJOURNALED"
UNCOMMITTED = "RECEIPT_INTENT_ORPHAN_UNCOMMITTED"
JOURNAL_TORN = "RECEIPT_JOURNAL_UNTERMINATED"
INTENT_TORN = "RECEIPT_INTENT_JOURNAL_UNTERMINATED"
SYNC_FAILED = "RECEIPT_RECOVERY_SYNC_FAILED"


def _record(rec, *, url, raw, when=T0):
    rec.clock = lambda: when
    with patch.object(ms, "_trusted_now", lambda: when):
        return rec.record(url=url, raw=raw, fetch_started_at=when,
                          received_at=when + timedelta(seconds=1))


def _seed_root(base: Path) -> Path:
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
    try:
        entries = ms.verify_receipt_journal(root, verifier_now=LATER)
    except ms.MLBSourceError as exc:
        return "refuse", str(exc)
    return "verify", [e["sequence"] for e in entries]


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
        if state["dw"] == 0:
            return real_fsync(fd)
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
    assert marker.read_text() == f"{mode}:{param}"
    return root


def _sabotaged_verify(root: Path):
    """Verify with every fsync failing; return the (outcome, detail)."""
    with patch.object(os, "fsync",
                      side_effect=OSError("injected sync failure")):
        return _verify_status(root)


# ---------------------------------------------------------------------------
# Discriminators: acceptance must complete the durability chain
# ---------------------------------------------------------------------------

def test_b10_sync_failure_refuses_instead_of_accepting(tmp_path):
    """The B10 wedge: COMMIT visible, its fsync never ran. If the
    verifier's recovery sync cannot complete, the indeterminate chain
    is refused by name -- the unmodified verifier accepted silently."""
    root = _run_injection(tmp_path, "before_fsync", 9)
    assert _sabotaged_verify(root) == ("refuse", SYNC_FAILED)


def test_b11_sync_failure_refuses_instead_of_accepting(tmp_path):
    """Even with a fully durable COMMIT (death after the append),
    acceptance performs the recovery sync: a sync failure refuses."""
    root = _run_injection(tmp_path, "after_dw", 4)
    assert _sabotaged_verify(root) == ("refuse", SYNC_FAILED)


def test_untouched_root_sync_failure_refuses(tmp_path):
    """No crash at all: an ordinary committed root is still certified
    only through a completed chain once an intent journal exists."""
    root = _seed_root(tmp_path / "clean")
    assert _sabotaged_verify(root) == ("refuse", SYNC_FAILED)
    assert _verify_status(root) == ("verify", [1])


def test_acceptance_performs_chain_fsyncs(tmp_path):
    """The recovery sync is observed (journal, intent, directory >= 3
    fsync calls during verify of a B10 root), not merely asserted."""
    root = _run_injection(tmp_path, "before_fsync", 9)
    real = os.fsync
    called = []
    def tracked(fd):
        called.append(fd)
        return real(fd)
    with patch.object(os, "fsync", tracked):
        entries = ms.verify_receipt_journal(root, verifier_now=LATER)
    assert [e["sequence"] for e in entries] == [1, 2]
    assert len(called) >= 3


def test_recorder_front_door_applies_recovery(tmp_path):
    """MLBSourceCapture construction re-verifies: on a B10 root it
    succeeds only through the recovery sync, refuses by the sync name
    when the sync fails, and leaves the residue byte-identical."""
    root = _run_injection(tmp_path, "before_fsync", 9)
    before = _snapshot(root)
    with patch.object(os, "fsync",
                      side_effect=OSError("injected sync failure")):
        with patch.object(ms, "_trusted_now", lambda: LATER):
            with pytest.raises(ms.MLBSourceError) as excinfo:
                ms.MLBSourceCapture(root)
    assert str(excinfo.value) == SYNC_FAILED
    assert _snapshot(root) == before
    rec = ms.MLBSourceCapture(root, clock=lambda: T0)
    assert rec._sequence == 2
    assert _snapshot(root) == before


# ---------------------------------------------------------------------------
# Ordering pins: structural refusals precede (and survive) the sync
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mode,param,status", [
    ("before_fsync", 1, UNCOMMITTED),    # B1: BEGIN visible only
    ("before_fsync", 3, ORPHAN),         # B4: raw visible, no journal
    ("torn_dw", 3, JOURNAL_TORN),        # T3: torn journal line
    ("torn_dw", 4, INTENT_TORN),         # T4: torn COMMIT line
])
def test_structural_refusal_precedes_sync(tmp_path, mode, param, status):
    """With fsync sabotaged, torn/uncommitted residues still refuse by
    their structural names -- the recovery sync never masks them with
    its own name, because it runs only after every structural check."""
    root = _run_injection(tmp_path, mode, param)
    assert _sabotaged_verify(root) == ("refuse", status)
    assert _verify_status(root) == ("refuse", status)


def _intent_lines(root: Path) -> list[bytes]:
    return (root / ms.RECEIPT_INTENT_JOURNAL_NAME).read_bytes().splitlines()


def _rewrite_intents(root: Path, lines: list[bytes]) -> None:
    (root / ms.RECEIPT_INTENT_JOURNAL_NAME).write_bytes(b"\n".join(lines) + b"\n")


def test_duplicate_commit_keeps_intent_integrity_name(tmp_path):
    """BEGIN + COMMIT + COMMIT for one intent: refused as an unpaired
    terminal (RECEIPT_INTENT_ORPHAN_TERMINAL), not by the sync name and
    not accepted -- duplicate COMMITs cannot launder a second commit."""
    root = _seed_root(tmp_path / "dup_commit")
    lines = _intent_lines(root)
    assert len(lines) == 2  # BEGIN, COMMIT for receipt #1
    _rewrite_intents(root, lines + [lines[1]])
    assert _sabotaged_verify(root) == ("refuse", "RECEIPT_INTENT_ORPHAN_TERMINAL")
    assert _verify_status(root) == ("refuse", "RECEIPT_INTENT_ORPHAN_TERMINAL")


def test_duplicate_begin_keeps_intent_integrity_name(tmp_path):
    """BEGIN + BEGIN (while still open) + COMMIT for one intent:
    RECEIPT_INTENT_DUPLICATE_BEGIN."""
    root = _seed_root(tmp_path / "dup_begin")
    lines = _intent_lines(root)
    _rewrite_intents(root, [lines[0], lines[0], lines[1]])
    assert _verify_status(root) == ("refuse", "RECEIPT_INTENT_DUPLICATE_BEGIN")


def test_unpaired_commit_keeps_intent_integrity_name(tmp_path):
    """A COMMIT whose BEGIN was removed: RECEIPT_INTENT_ORPHAN_TERMINAL."""
    root = _seed_root(tmp_path / "orphan_commit")
    lines = _intent_lines(root)
    _rewrite_intents(root, [lines[1]])
    assert _verify_status(root) == ("refuse", "RECEIPT_INTENT_ORPHAN_TERMINAL")


def test_hostile_intent_path_refused_by_reader_name(tmp_path):
    """Intent path replaced by a symlink: the structural reader refuses
    it (RECEIPT_INTENT_JOURNAL_PATH_UNSAFE) before any sync could run;
    the sync's own no-follow checks are never the first line of defense."""
    root = _seed_root(tmp_path / "hostile")
    intent = root / ms.RECEIPT_INTENT_JOURNAL_NAME
    target = tmp_path / "hostile" / "elsewhere.jsonl"
    target.write_bytes(intent.read_bytes())
    intent.unlink()
    intent.symlink_to(target)
    assert _sabotaged_verify(root) == (
        "refuse", "RECEIPT_INTENT_JOURNAL_PATH_UNSAFE")


# ---------------------------------------------------------------------------
# Posture pins: recovery never rewrites, never grants authority
# ---------------------------------------------------------------------------

def test_recovery_leaves_bytes_identical_and_root_extensible(tmp_path):
    """A successful recovery sync persists bytes; it does not modify
    them. The recovered root verifies twice and accepts receipt #3."""
    root = _run_injection(tmp_path, "before_fsync", 9)
    before = _snapshot(root)
    assert _verify_status(root) == ("verify", [1, 2])
    assert _snapshot(root) == before
    assert _verify_status(root) == ("verify", [1, 2])
    assert _snapshot(root) == before
    rec = ms.MLBSourceCapture(root, clock=lambda: T0)
    _record(rec, url="https://x/api/v1/game/5555/boxscore",
            raw=b'{"game":5555}')
    assert _verify_status(root) == ("verify", [1, 2, 3])


def test_legacy_journal_only_root_needs_no_sync(tmp_path):
    """A root from the pre-intent protocol (journal + raw, no intent
    journal) verifies with ZERO fsync calls: the sync does not engage
    and grants no authority where no COMMIT durability is in question."""
    root = _seed_root(tmp_path / "legacy")
    (root / ms.RECEIPT_INTENT_JOURNAL_NAME).unlink()
    (root / ms.RECEIPT_JOURNAL_LOCK_NAME).unlink(missing_ok=True)
    real = os.fsync
    called = []
    def tracked(fd):
        called.append(fd)
        return real(fd)
    with patch.object(os, "fsync", tracked):
        entries = ms.verify_receipt_journal(root, verifier_now=LATER)
    assert [e["sequence"] for e in entries] == [1]
    assert called == []
