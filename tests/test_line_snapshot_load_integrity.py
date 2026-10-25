"""Synthetic storage-integrity tests; hashes do not authenticate capture times."""
import json
import pytest
from sportsedge.line_snapshots import (SnapshotError, build_snapshot, append_snapshot,
                                      load_snapshots, snapshot_path)


def saved(tmp_path):
    record = build_snapshot(sport='nfl', issue_number=12,
        body='A @ B\nCaptured: 2026-10-25T12:00:00Z', title='NFL',
        game={'away':'A','home':'B'}, board=[{'price':-110}],
        picks=[{'pick':'OVER','price':-110}], recorded_at='2026-10-25T12:01:00Z')
    append_snapshot(record, root=tmp_path)
    return record, snapshot_path('nfl',12,tmp_path)


def test_valid_snapshot_and_idempotent_append(tmp_path):
    record, _ = saved(tmp_path)
    assert load_snapshots('nfl',12,tmp_path) == [record]
    assert append_snapshot(record,root=tmp_path) is False


@pytest.mark.parametrize('field,value', [('body','altered'),('board',[]),('picks',[]),
    ('captured_at','2026-10-24T12:00:00Z'),('game',{})])
def test_tampered_content_refuses(tmp_path,field,value):
    record,path = saved(tmp_path)
    record[field]=value
    path.write_text(json.dumps(record)+'\n')
    with pytest.raises(SnapshotError,match='DIGEST_MISMATCH'):
        load_snapshots('nfl',12,tmp_path)


@pytest.mark.parametrize('field,value',[('sport','nba'),('issue_number',13),
    ('issue_number',12.0),('schema','unknown')])
def test_wrong_identity_refuses(tmp_path,field,value):
    record,path=saved(tmp_path);record[field]=value
    path.write_text(json.dumps(record)+'\n')
    with pytest.raises(SnapshotError,match='IDENTITY_MISMATCH'):
        load_snapshots('nfl',12,tmp_path)


@pytest.mark.parametrize('text',['{broken','[]','null'])
def test_malformed_records_refuse_entire_load(tmp_path,text):
    _,path=saved(tmp_path)
    with path.open('a') as f: f.write(text+'\n')
    with pytest.raises(SnapshotError): load_snapshots('nfl',12,tmp_path)
