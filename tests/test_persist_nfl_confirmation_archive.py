import pytest
from scripts.persist_nfl_confirmation_archive import archive_paths
from scripts.persist_forward_evidence_data_branch import PersistenceBlocked


def test_append_log_gets_unique_snapshot_without_mutating_captures(tmp_path):
    captures = tmp_path / 'data/nfl_2026_confirmation/captures'
    captures.mkdir(parents=True)
    (captures / 'opener.json').write_text('{"original":true}')
    log = captures / 'attempts.jsonl'
    log.write_text('first\n')
    first = archive_paths(tmp_path, '123', '1')
    assert not any(p.endswith('/attempts.jsonl') for p in first)
    assert str((captures / 'opener.json').relative_to(tmp_path)) in first
    assert (tmp_path / first[-1]).read_text() == 'first\n'
    assert archive_paths(tmp_path, '123', '1') == first
    log.write_text('first\nsecond\n')
    second = archive_paths(tmp_path, '124', '1')
    assert (tmp_path / first[-1]).read_text() == 'first\n'
    assert (tmp_path / second[-1]).read_text() == 'first\nsecond\n'
    with pytest.raises(PersistenceBlocked, match='IDENTITY_COLLISION'):
        archive_paths(tmp_path, '123', '1')


def test_no_files_or_invalid_run_identity(tmp_path):
    assert archive_paths(tmp_path, '123', '1') == []
    with pytest.raises(PersistenceBlocked, match='IDENTITY_REQUIRED'):
        archive_paths(tmp_path, '../bad', '1')
