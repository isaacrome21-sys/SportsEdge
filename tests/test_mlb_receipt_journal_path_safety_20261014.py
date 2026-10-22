"""Path-safety regression battery for the receipt-journal hardening port.

Pins the properties ported onto the intent-journal build from the Codex
durability build (crosscheck: RECEIPT_JOURNAL_CROSSCHECK.md). Before the
port, ``verify_receipt_journal`` read the journal with a plain
``read_bytes()``: a FIFO at the journal path blocked verification
indefinitely, a directory leaked an unnamed ``IsADirectoryError``, a
dangling symlink was silently treated as "no journal", non-UTF-8 bytes
leaked an unnamed ``UnicodeDecodeError``, and an oversized journal was
reported under the wrong name. The writer lock and the raw-payload
write were likewise plain path opens that followed planted symlinks.

Every malformed-path case must now refuse with a NAMED
``MLBSourceError`` status, with no hangs and no unnamed exception
leaks. Cases that would hang a naive implementation (FIFOs) run in a
subprocess under a hard timeout so this suite can never hang itself.
"""
import os
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from sportsedge import mlb_source as ms

NOW = datetime(2026, 10, 13, 16, tzinfo=timezone.utc)
REPO_ROOT = Path(__file__).resolve().parents[1]

_CHILD = textwrap.dedent(
    """
    import os, sys
    from datetime import datetime, timezone
    from pathlib import Path
    from unittest.mock import patch
    from sportsedge import mlb_source as ms

    NOW = datetime(2026, 10, 13, 16, tzinfo=timezone.utc)
    base = Path(sys.argv[1])

    def attempt(label, fn):
        try:
            fn()
        except ms.MLBSourceError as exc:
            print(f"{label} {exc}", flush=True)
        except BaseException as exc:  # unnamed leak detector
            print(f"{label} UNNAMED:{type(exc).__name__}", flush=True)
        else:
            print(f"{label} NO_RAISE", flush=True)

    root = base / "fifo_journal"; root.mkdir()
    os.mkfifo(root / ms.RECEIPT_JOURNAL_NAME)
    attempt("FIFO_JOURNAL", lambda: ms.verify_receipt_journal(root, verifier_now=NOW))

    root = base / "fifo_intent"; root.mkdir()
    os.mkfifo(root / ms.RECEIPT_INTENT_JOURNAL_NAME)
    attempt("FIFO_INTENT", lambda: ms.verify_receipt_journal(root, verifier_now=NOW))

    root = base / "fifo_lock"; root.mkdir()
    os.mkfifo(root / ms.RECEIPT_JOURNAL_LOCK_NAME)
    def fifo_lock():
        with patch.object(ms, "_trusted_now", return_value=NOW):
            recorder = ms.MLBSourceCapture(root)
            recorder.record(url="https://example.test/a", raw=b"{}",
                            fetch_started_at=NOW, received_at=NOW)
    attempt("FIFO_LOCK", fifo_lock)
    print("DONE", flush=True)
    """
)


def test_fifo_paths_refuse_by_name_without_hanging(tmp_path):
    """FIFO at the journal, intent-journal or lock path: named refusal,
    no indefinite block. Runs in a subprocess with a hard timeout --
    pre-port, the journal/intent reads blocked forever on these."""
    script = tmp_path / "fifo_probe.py"
    script.write_text(_CHILD)
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
    proc = subprocess.run(
        [sys.executable, str(script), str(tmp_path)],
        capture_output=True, text=True, timeout=60, env=env)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "DONE" in out
    assert "FIFO_JOURNAL RECEIPT_JOURNAL_PATH_UNSAFE" in out
    assert "FIFO_INTENT RECEIPT_INTENT_JOURNAL_PATH_UNSAFE" in out
    assert "FIFO_LOCK RECEIPT_LOCK_PATH_UNSAFE" in out
    assert "UNNAMED" not in out
    assert "NO_RAISE" not in out


def test_directory_journal_path_refused_by_name(tmp_path):
    (tmp_path / ms.RECEIPT_JOURNAL_NAME).mkdir()
    with pytest.raises(ms.MLBSourceError, match="RECEIPT_JOURNAL_PATH_UNSAFE"):
        ms.verify_receipt_journal(tmp_path, verifier_now=NOW)


def test_dangling_symlink_journal_refused_by_name(tmp_path):
    (tmp_path / ms.RECEIPT_JOURNAL_NAME).symlink_to(tmp_path / "missing")
    with pytest.raises(ms.MLBSourceError, match="RECEIPT_JOURNAL_PATH_UNSAFE"):
        ms.verify_receipt_journal(tmp_path, verifier_now=NOW)


def test_symlink_to_valid_journal_still_refused(tmp_path):
    """The journal path is never followed, even to a well-formed file."""
    real = tmp_path / "real"
    real.mkdir()
    with patch.object(ms, "_trusted_now", return_value=NOW):
        recorder = ms.MLBSourceCapture(real)
        recorder.record(url="https://example.test/a", raw=b"{}",
                        fetch_started_at=NOW, received_at=NOW)
    linked = tmp_path / "linked"
    linked.mkdir()
    (linked / ms.RECEIPT_JOURNAL_NAME).symlink_to(real / ms.RECEIPT_JOURNAL_NAME)
    with pytest.raises(ms.MLBSourceError, match="RECEIPT_JOURNAL_PATH_UNSAFE"):
        ms.verify_receipt_journal(linked, verifier_now=NOW)


def test_oversized_journal_refused_by_name(tmp_path):
    with open(tmp_path / ms.RECEIPT_JOURNAL_NAME, "wb") as handle:
        handle.truncate(ms.MAX_RECEIPT_RAW_BYTES + 1)
    with pytest.raises(ms.MLBSourceError, match="RECEIPT_JOURNAL_SIZE_INVALID"):
        ms.verify_receipt_journal(tmp_path, verifier_now=NOW)


def test_non_utf8_journal_refused_as_corrupt(tmp_path):
    (tmp_path / ms.RECEIPT_JOURNAL_NAME).write_bytes(b"\xff\xfe\x00\n")
    with pytest.raises(ms.MLBSourceError, match="RECEIPT_JOURNAL_CORRUPT"):
        ms.verify_receipt_journal(tmp_path, verifier_now=NOW)


def test_directory_intent_journal_refused_by_name(tmp_path):
    (tmp_path / ms.RECEIPT_INTENT_JOURNAL_NAME).mkdir()
    with pytest.raises(ms.MLBSourceError,
                       match="RECEIPT_INTENT_JOURNAL_PATH_UNSAFE"):
        ms.verify_receipt_journal(tmp_path, verifier_now=NOW)


def test_symlinked_lock_path_refused_by_name(tmp_path):
    target = tmp_path / "elsewhere.lock"
    target.write_bytes(b"")
    (tmp_path / ms.RECEIPT_JOURNAL_LOCK_NAME).symlink_to(target)
    with patch.object(ms, "_trusted_now", return_value=NOW):
        recorder = ms.MLBSourceCapture(tmp_path)
        with pytest.raises(ms.MLBSourceError, match="RECEIPT_LOCK_PATH_UNSAFE"):
            recorder.record(url="https://example.test/a", raw=b"{}",
                            fetch_started_at=NOW, received_at=NOW)


def test_durable_write_refuses_fifo_and_caps_append(tmp_path):
    fifo = tmp_path / "planted"
    os.mkfifo(fifo)
    with pytest.raises(ms.MLBSourceError, match="RECEIPT_WRITE_PATH_UNSAFE"):
        ms._durable_receipt_write(fifo, b"x", append=True)
    capped = tmp_path / "journal.jsonl"
    with open(capped, "wb") as handle:
        handle.truncate(ms.MAX_RECEIPT_RAW_BYTES)
    with pytest.raises(ms.MLBSourceError, match="RECEIPT_JOURNAL_SIZE_INVALID"):
        ms._durable_receipt_write(capped, b"x", append=True)


def test_resync_existing_raw_refuses_fifo(tmp_path):
    fifo = tmp_path / "planted.json"
    os.mkfifo(fifo)
    with pytest.raises(ms.MLBSourceError, match="RECEIPT_WRITE_PATH_UNSAFE"):
        ms._resync_existing_receipt_raw(fifo)
    regular = tmp_path / "real.json"
    regular.write_bytes(b"{}")
    ms._resync_existing_receipt_raw(regular)  # must not raise


def test_record_verify_roundtrip_through_descriptor_paths(tmp_path):
    with patch.object(ms, "_trusted_now", return_value=NOW):
        recorder = ms.MLBSourceCapture(tmp_path)
        recorder.record(url="https://example.test/a", raw=b"{}",
                        fetch_started_at=NOW, received_at=NOW)
        rows = ms.verify_receipt_journal(tmp_path, verifier_now=NOW)
    assert len(rows) == 1
    assert rows[0]["url"] == "https://example.test/a"
