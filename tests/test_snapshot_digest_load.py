"""Snapshot ledger integrity tests (synthetic, not authenticated receipts)."""
import json
import pytest
from sportsedge.line_snapshots import build_snapshot, append_snapshot, load_snapshots, SnapshotError


def sample():
    return build_snapshot(sport="nfl", issue_number=991001,
        body="Away @ Home\nCaptured: 2026-10-25T11:00:00Z",
        title="synthetic", game={"away": "Away", "home": "Home"},
        board=[{"price": -110}], picks=[{"pick": "Over 50.5", "price": -110}],
        recorded_at="2026-10-25T11:01:00Z")


def test_roundtrip_and_tamper_refused(tmp_path):
    record = sample()
    assert append_snapshot(record, root=tmp_path)
    assert load_snapshots("nfl", 991001, root=tmp_path) == [record]
    path = tmp_path / "nfl" / "991001.jsonl"
    tampered = json.loads(path.read_text())
    tampered["board"][0]["price"] = -900
    path.write_text(json.dumps(tampered) + "\n")
    with pytest.raises(SnapshotError, match="SNAPSHOT_DIGEST_MISMATCH"):
        load_snapshots("nfl", 991001, root=tmp_path)


def test_malformed_or_missing_digest_refused(tmp_path):
    path = tmp_path / "nfl" / "991001.jsonl"
    path.parent.mkdir(parents=True)
    for line, reason in [('{"oops":', "SNAPSHOT_JSON_INVALID"),
                         (json.dumps({"board": []}), "SNAPSHOT_DIGEST_MISSING")]:
        path.write_text(line + "\n")
        with pytest.raises(SnapshotError, match=reason):
            load_snapshots("nfl", 991001, root=tmp_path)
