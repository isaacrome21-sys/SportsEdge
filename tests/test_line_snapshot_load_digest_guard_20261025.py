"""Synthetic stored-record integrity checks; no authenticated DK or receipt claim."""
import json

import pytest

from sportsedge.line_snapshots import (
    SnapshotError, append_snapshot, build_snapshot, load_snapshots, snapshot_path,
)


def _fixture():
    return build_snapshot(
        sport="nfl", issue_number=999991,
        body="Away @ Home\nCaptured: 2026-10-25T11:00:00Z",
        title="[NFL LINES] Away @ Home",
        game={"away": "Away", "home": "Home"},
        board=[{"market": "TOTAL", "price": -110}],
        picks=[{"pick": "Over 50.5", "price": -110}],
        recorded_at="2026-10-25T11:01:00Z",
    )


def _write_one(tmp_path, change):
    record = _fixture()
    assert append_snapshot(record, root=tmp_path)
    path = snapshot_path("nfl", 999991, tmp_path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    change(saved)
    path.write_text(json.dumps(saved) + "\n", encoding="utf-8")


def test_valid_stored_record_roundtrips_and_deduplicates(tmp_path):
    record = _fixture()
    assert append_snapshot(record, root=tmp_path)
    assert not append_snapshot(record, root=tmp_path)
    assert load_snapshots("nfl", 999991, root=tmp_path) == [record]


@pytest.mark.parametrize("field", ["board", "picks", "body", "captured_at"])
def test_core_content_mutation_without_new_digest_fails_closed(tmp_path, field):
    def corrupt(row):
        if field == "board":
            row["board"][0]["price"] = -900
        elif field == "picks":
            row["picks"][0]["price"] = -900
        elif field == "body":
            row["body"] = "changed after writing"
        else:
            row["captured_at"] = "2026-10-25T10:59:00+00:00"

    _write_one(tmp_path, corrupt)
    with pytest.raises(SnapshotError, match="SNAPSHOT_DIGEST_MISMATCH"):
        load_snapshots("nfl", 999991, root=tmp_path)


@pytest.mark.parametrize("field,value,reason", [
    ("content_sha256", None, "SNAPSHOT_DIGEST_MISMATCH"),
    ("schema", "incorrect.schema", "SNAPSHOT_SCHEMA_INVALID"),
    ("sport", "cfb", "SNAPSHOT_IDENTITY_MISMATCH"),
    ("issue_number", 999992, "SNAPSHOT_IDENTITY_MISMATCH"),
    ("issue_number", True, "SNAPSHOT_IDENTITY_MISMATCH"),
])
def test_metadata_and_digest_conflicts_fail_closed(tmp_path, field, value, reason):
    _write_one(tmp_path, lambda row: row.__setitem__(field, value))
    with pytest.raises(SnapshotError, match=reason):
        load_snapshots("nfl", 999991, root=tmp_path)


def test_missing_required_field_fails_closed(tmp_path):
    _write_one(tmp_path, lambda row: row.pop("board"))
    with pytest.raises(SnapshotError, match="SNAPSHOT_FIELDS_MISSING"):
        load_snapshots("nfl", 999991, root=tmp_path)


def test_invalid_json_or_nonobject_fails_closed(tmp_path):
    record = _fixture()
    append_snapshot(record, root=tmp_path)
    path = snapshot_path("nfl", 999991, tmp_path)
    path.write_text("not json\n", encoding="utf-8")
    with pytest.raises(SnapshotError, match="SNAPSHOT_JSON_INVALID"):
        load_snapshots("nfl", 999991, root=tmp_path)
    path.write_text("[]\n", encoding="utf-8")
    with pytest.raises(SnapshotError, match="SNAPSHOT_RECORD_INVALID"):
        load_snapshots("nfl", 999991, root=tmp_path)
