from datetime import datetime, timezone

import pytest

from sportsedge.mlb_market_snapshot import DEFAULT_MARKETS, build_market_snapshot
from sportsedge.mlb_snapshot_store import DuplicateSnapshotError, get_by_hash, get_latest, list_snapshots, read_snapshot_bytes, write_snapshot
from sportsedge.mlb_validation_dashboard import build_dashboard_row


def _row(market, status="Insufficient Evidence"):
    return build_dashboard_row(market=market, rows=[], predictive_status=status,
        infrastructure_status="Unknown", model_sha="model", feature_sha="feature",
        last_durable_evidence_timestamp=None, uncertainty_enabled=False, gate_evaluator_sha="gate")


def _snapshot(*, notes=None, status="Insufficient Evidence"):
    return build_market_snapshot(rows=[_row(m, status) for m in DEFAULT_MARKETS], git_sha="git", branch="research",
        evaluator_sha="eval", model_sha="model", feature_sha="feature", notes=notes,
        snapshot_timestamp=datetime(2026, 8, 21, 22, 45, tzinfo=timezone.utc))


def test_write_snapshot_then_manifest_index(tmp_path):
    s = _snapshot()
    a = write_snapshot(s, root=tmp_path)
    entries = list_snapshots(root=tmp_path)
    assert len(entries) == 1
    assert entries[0].content_hash == s.content_sha256
    assert get_by_hash(s.content_sha256, root=tmp_path) == entries[0]
    assert get_latest(root=tmp_path) == entries[0]
    assert read_snapshot_bytes(entries[0], root=tmp_path) == (s.to_json() + "\n").encode()


def test_identical_content_rejected_as_duplicate(tmp_path):
    s = _snapshot()
    write_snapshot(s, root=tmp_path)
    with pytest.raises(DuplicateSnapshotError):
        write_snapshot(s, root=tmp_path)
    assert len(list_snapshots(root=tmp_path)) == 1


def test_same_timestamp_different_content_gets_distinct_hash_path(tmp_path):
    a = write_snapshot(_snapshot(notes="one"), root=tmp_path)
    b = write_snapshot(_snapshot(notes="two"), root=tmp_path)
    assert a.path != b.path
    assert a.content_hash != b.content_hash
    assert len(list_snapshots(root=tmp_path)) == 2


def test_manifest_filters_market_coverage(tmp_path):
    write_snapshot(_snapshot(), root=tmp_path)
    assert len(list_snapshots(root=tmp_path, market="NRFI")) == 1
    assert list_snapshots(root=tmp_path, market="NBA") == []


def test_no_temp_snapshot_visible_after_success(tmp_path):
    write_snapshot(_snapshot(), root=tmp_path)
    assert not list(tmp_path.rglob("*.tmp"))
