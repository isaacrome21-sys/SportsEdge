"""Offline local durability/concurrency tests; no timestamp authority claims."""
import multiprocessing
import os
import stat
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sportsedge import mlb_source as ms

NOW = datetime(2026, 10, 13, 16, tzinfo=timezone.utc)


def _worker(root, barrier, index):
    with patch.object(ms, '_trusted_now', return_value=NOW):
        recorder = ms.MLBSourceCapture(root)
        barrier.wait(timeout=10)
        recorder.record(url=f'https://example.test/{index}', raw=b'{}',
                        fetch_started_at=NOW, received_at=NOW)


def test_process_writers_refresh_sequence_and_chain(tmp_path):
    ctx = multiprocessing.get_context('fork')
    barrier = ctx.Barrier(4)
    workers = [ctx.Process(target=_worker, args=(tmp_path, barrier, i)) for i in range(4)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(15)
        if worker.is_alive():
            worker.terminate()
            worker.join()
            pytest.fail('writer hung')
        assert worker.exitcode == 0
    rows = ms.verify_receipt_journal(tmp_path, verifier_now=NOW)
    assert [r['sequence'] for r in rows] == [1, 2, 3, 4]
    assert len({r['url'] for r in rows}) == 4


@pytest.mark.parametrize('kind', ['fifo', 'directory', 'symlink', 'oversized'])
def test_unsafe_journal_rejected_without_read(tmp_path, kind):
    path = tmp_path / ms.RECEIPT_JOURNAL_NAME
    if kind == 'fifo':
        os.mkfifo(path)
    elif kind == 'directory':
        path.mkdir()
    elif kind == 'symlink':
        path.symlink_to(tmp_path / 'missing')
    else:
        with path.open('wb') as handle:
            handle.truncate(ms.MAX_RECEIPT_RAW_BYTES + 1)
    with pytest.raises(ms.MLBSourceError, match='RECEIPT_JOURNAL_(PATH_UNSAFE|SIZE_INVALID)'):
        ms.verify_receipt_journal(tmp_path, verifier_now=NOW)


def test_raw_and_directory_durable_before_journal_ack(tmp_path):
    events = []
    real_sync = os.fsync
    def sync(fd):
        info = os.fstat(fd)
        events.append('dir' if stat.S_ISDIR(info.st_mode) else 'file')
        real_sync(fd)
    with patch.object(ms, '_trusted_now', return_value=NOW), patch.object(os, 'fsync', side_effect=sync):
        recorder = ms.MLBSourceCapture(tmp_path)
        recorder.record(url='https://example.test/a', raw=b'{}',
                        fetch_started_at=NOW, received_at=NOW)
    assert events == ['file', 'dir', 'file', 'dir']
    assert len(ms.verify_receipt_journal(tmp_path, verifier_now=NOW)) == 1
    assert recorder.manifest()['external_time_anchor'] is False


def test_failed_raw_sync_never_appends_receipt(tmp_path):
    with patch.object(ms, '_trusted_now', return_value=NOW):
        recorder = ms.MLBSourceCapture(tmp_path)
        with patch.object(os, 'fsync', side_effect=OSError('disk failed')):
            with pytest.raises(OSError, match='disk failed'):
                recorder.record(url='https://example.test/a', raw=b'{}',
                                fetch_started_at=NOW, received_at=NOW)
    assert not (tmp_path / ms.RECEIPT_JOURNAL_NAME).exists()
    assert recorder.records == []


def test_stale_recorder_cannot_replay_receipt(tmp_path):
    with patch.object(ms, '_trusted_now', return_value=NOW):
        first, second = ms.MLBSourceCapture(tmp_path), ms.MLBSourceCapture(tmp_path)
        args = dict(url='https://example.test/a', raw=b'{}', fetch_started_at=NOW, received_at=NOW)
        first.record(**args)
        with pytest.raises(ms.MLBSourceError, match='RECEIPT_DUPLICATE_REPLAY'):
            second.record(**args)
    assert len(ms.verify_receipt_journal(tmp_path, verifier_now=NOW)) == 1


def test_retry_after_failed_raw_sync_resyncs_raw_before_receipt(tmp_path):
    args = dict(url='https://example.test/a', raw=b'{}',
                fetch_started_at=NOW, received_at=NOW)
    events = []
    real_sync = os.fsync
    def sync(fd):
        events.append('dir' if stat.S_ISDIR(os.fstat(fd).st_mode) else 'file')
        real_sync(fd)
    with patch.object(ms, '_trusted_now', return_value=NOW):
        recorder = ms.MLBSourceCapture(tmp_path)
        with patch.object(os, 'fsync', side_effect=OSError('disk failed')):
            with pytest.raises(OSError):
                recorder.record(**args)
        with patch.object(os, 'fsync', side_effect=sync):
            recorder.record(**args)
    assert events == ['file', 'dir', 'file', 'dir']
    assert len(ms.verify_receipt_journal(tmp_path, verifier_now=NOW)) == 1
