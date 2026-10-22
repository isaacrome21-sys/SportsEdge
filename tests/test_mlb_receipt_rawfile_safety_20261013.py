"""Offline adversarial raw-file verification for MLB receipt archives.

Never fetches StatsAPI or Odds API; no capture or betting activation.
"""
import json
import os
import signal
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from sportsedge import mlb_source as ms


T0 = datetime(2026, 10, 13, 16, tzinfo=timezone.utc)
URL = "https://x/api/v1/schedule"


def _save(tmp_path):
    with patch.object(ms, "_trusted_now", return_value=T0):
        recorder = ms.MLBSourceCapture(tmp_path, clock=lambda: T0)
        return recorder.record(url=URL, raw=b'{"dates":[]}',
                               fetch_started_at=T0, received_at=T0)


def _verify(tmp_path):
    return ms.verify_receipt_journal(tmp_path, verifier_now=T0 + timedelta(minutes=5))


def test_regular_raw_receipt_is_still_accepted(tmp_path):
    _save(tmp_path)
    assert len(_verify(tmp_path)) == 1


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="Requires POSIX FIFO")
def test_replaced_raw_fifo_fails_without_blocking(tmp_path):
    saved = _save(tmp_path)
    path = saved.path
    os.unlink(path)
    os.mkfifo(path)
    # The alarm is a defensive guard: the pre-fix implementation blocked on
    # Path.read_bytes, which must never hang the full hosted test suite.
    def timeout(*_):
        raise AssertionError("receipt verifier blocked on FIFO")
    previous = signal.signal(signal.SIGALRM, timeout)
    signal.alarm(3)
    try:
        with pytest.raises(ms.MLBSourceError, match="RECEIPT_RAW_PATH_UNSAFE"):
            _verify(tmp_path)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def test_replaced_raw_directory_fails_closed(tmp_path):
    saved = _save(tmp_path)
    os.unlink(saved.path)
    os.mkdir(saved.path)
    with pytest.raises(ms.MLBSourceError, match="RECEIPT_RAW_PATH_UNSAFE"):
        _verify(tmp_path)


def test_replaced_raw_symlink_fails_closed(tmp_path):
    saved = _save(tmp_path)
    os.unlink(saved.path)
    target = tmp_path / "outside.json"
    target.write_bytes(b'{"dates":[]}')
    os.symlink(target, saved.path)
    with pytest.raises(ms.MLBSourceError, match="RECEIPT_RAW_PATH_UNSAFE"):
        _verify(tmp_path)


def test_sparse_oversized_raw_is_rejected_before_read(tmp_path):
    saved = _save(tmp_path)
    with open(saved.path, "wb") as handle:
        handle.truncate(ms.MAX_RECEIPT_RAW_BYTES + 1)
    with pytest.raises(ms.MLBSourceError, match="RECEIPT_RAW_SIZE_INVALID"):
        _verify(tmp_path)


@pytest.mark.parametrize("wrong_size", [True, "12", -1, ms.MAX_RECEIPT_RAW_BYTES + 1])
def test_malformed_expected_raw_length_fails_even_if_resigned(tmp_path, wrong_size):
    _save(tmp_path)
    manifest = tmp_path / ms.RECEIPT_JOURNAL_NAME
    row = json.loads(manifest.read_text().strip())
    row["byte_length"] = wrong_size
    row["record_sha256"] = ms._record_hash(row)
    manifest.write_text(json.dumps(row) + "\n")
    with pytest.raises(ms.MLBSourceError, match="RECEIPT_RAW_SIZE_INVALID"):
        _verify(tmp_path)
