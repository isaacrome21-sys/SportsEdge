"""Offline local durability/concurrency tests; no timestamp authority claims."""
import json
import multiprocessing
import os
import stat
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sportsedge import mlb_source as ms

NOW = datetime(2026, 10, 13, 16, tzinfo=timezone.utc)


def _sync_target(root, fd):
    """Identify the real inode being synced, including the intent state."""
    info = os.fstat(fd)
    if stat.S_ISDIR(info.st_mode):
        return 'dir'
    for name, label in [(ms.RECEIPT_INTENT_JOURNAL_NAME, 'intent'),
                        (ms.RECEIPT_JOURNAL_NAME, 'journal')]:
        path = root / name
        if path.exists() and os.path.samestat(info, path.stat()):
            if label == 'intent':
                return 'intent:' + json.loads(path.read_bytes().splitlines()[-1])['state']
            return label
    assert any(os.path.samestat(info, path.stat()) for path in root.glob('*.json'))
    return 'raw'


def _assert_durable_append_order(events):
    # Require each data/intent file and its directory entry to be durable
    # before the next stage. Extra directory syncs are harmless; counting
    # anonymous file syncs would not catch raw/journal reordering.
    stages = ['intent:BEGIN', 'raw', 'journal', 'intent:COMMIT']
    positions = [events.index(stage) for stage in stages]
    assert positions == sorted(positions)
    for start, end in zip(positions, positions[1:] + [len(events)]):
        assert 'dir' in events[start + 1:end], (stages, events)


def _fail_raw_sync(root, real_sync, attempts):
    def sync(fd):
        if _sync_target(root, fd) == 'raw':
            attempts.append('raw')
            raise OSError('raw disk failed')
        real_sync(fd)
    return sync


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
        events.append(_sync_target(tmp_path, fd))
        real_sync(fd)
    with patch.object(ms, '_trusted_now', return_value=NOW), patch.object(os, 'fsync', side_effect=sync):
        recorder = ms.MLBSourceCapture(tmp_path)
        recorder.record(url='https://example.test/a', raw=b'{}',
                        fetch_started_at=NOW, received_at=NOW)
    _assert_durable_append_order(events)
    assert len(ms.verify_receipt_journal(tmp_path, verifier_now=NOW)) == 1
    assert recorder.manifest()['external_time_anchor'] is False


def test_failed_raw_sync_never_appends_receipt(tmp_path):
    attempts = []
    with patch.object(ms, '_trusted_now', return_value=NOW):
        recorder = ms.MLBSourceCapture(tmp_path)
        with patch.object(os, 'fsync', side_effect=_fail_raw_sync(tmp_path, os.fsync, attempts)):
            with pytest.raises(OSError, match='raw disk failed'):
                recorder.record(url='https://example.test/a', raw=b'{}',
                                fetch_started_at=NOW, received_at=NOW)
    assert attempts == ['raw']  # BEGIN succeeded; the fault reached the payload.
    assert not (tmp_path / ms.RECEIPT_JOURNAL_NAME).exists()
    assert not list(tmp_path.glob('*.json'))
    intents = [json.loads(line) for line in
               (tmp_path / ms.RECEIPT_INTENT_JOURNAL_NAME).read_bytes().splitlines()]
    assert [i['state'] for i in intents] == ['BEGIN', 'ABORT']
    assert ms.verify_receipt_journal(tmp_path, verifier_now=NOW) == []
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
    attempts = []
    real_sync = os.fsync
    def sync(fd):
        events.append(_sync_target(tmp_path, fd))
        real_sync(fd)
    with patch.object(ms, '_trusted_now', return_value=NOW):
        recorder = ms.MLBSourceCapture(tmp_path)
        with patch.object(os, 'fsync', side_effect=_fail_raw_sync(tmp_path, real_sync, attempts)):
            with pytest.raises(OSError, match='raw disk failed'):
                recorder.record(**args)
        assert attempts == ['raw']
        assert recorder.records == []
        assert not list(tmp_path.glob('*.json'))
        with patch.object(os, 'fsync', side_effect=sync):
            recorder.record(**args)
    _assert_durable_append_order(events)
    rows = ms.verify_receipt_journal(tmp_path, verifier_now=NOW)
    assert [r['sequence'] for r in rows] == [1]
    assert len(recorder.records) == 1


def test_persistent_sync_failure_reports_failed_rollback(tmp_path):
    # Preserve the old all-fsyncs-fail scenario separately: it fails BEGIN
    # and ABORT, so the named rollback failure must reach the caller.
    with patch.object(ms, '_trusted_now', return_value=NOW):
        recorder = ms.MLBSourceCapture(tmp_path)
        with patch.object(os, 'fsync', side_effect=OSError('disk failed')):
            with pytest.raises(ms.MLBSourceError,
                               match='^RECEIPT_APPEND_ROLLBACK_FAILED:intent:OSError$'):
                recorder.record(url='https://example.test/a', raw=b'{}',
                                fetch_started_at=NOW, received_at=NOW)
    assert recorder.records == []
    assert not (tmp_path / ms.RECEIPT_JOURNAL_NAME).exists()
    assert not list(tmp_path.glob('*.json'))
