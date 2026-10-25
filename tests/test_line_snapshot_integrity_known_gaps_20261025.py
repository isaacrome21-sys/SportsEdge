"""Research-only executable security regressions; xfail until integrity is enforced.

These fixtures are synthetic and do not establish authentic DraftKings evidence.
"""
import pytest

from sportsedge.line_snapshots import (
    build_snapshot, append_snapshot, load_snapshots, pre_start, SnapshotError,
)


def _record():
    return build_snapshot(
        sport="cfb", issue_number=999999,
        body="Away @ Home\nCaptured: 2026-10-25T11:00:00Z",
        title="synthetic", game={"away": "Away", "home": "Home"},
        board=[{"market": "TOTAL", "price": -110}],
        picks=[{"pick": "Over 50.5", "price": -110}],
        recorded_at="2026-10-25T11:01:00Z",
    )


@pytest.mark.xfail(strict=True, reason="load_snapshots currently trusts stored digest without recomputation")
def test_modified_board_is_rejected_on_load(tmp_path):
    import json
    record = _record()
    assert append_snapshot(record, root=tmp_path)
    path = tmp_path / "cfb" / "999999.jsonl"
    tampered = json.loads(path.read_text())
    tampered["board"][0]["price"] = -900
    path.write_text(json.dumps(tampered) + "\n")
    with pytest.raises(SnapshotError):
        load_snapshots("cfb", 999999, root=tmp_path)


@pytest.mark.xfail(strict=True, reason="recorded_at is not bound to the stored content hash or external receipt")
def test_late_receipt_timestamp_rewrite_cannot_make_pregame_evidence(tmp_path):
    import json
    record = _record()
    record["recorded_at"] = "2026-10-25T13:00:00Z"
    assert append_snapshot(record, root=tmp_path)
    path = tmp_path / "cfb" / "999999.jsonl"
    tampered = json.loads(path.read_text())
    original_hash = tampered["content_sha256"]
    tampered["recorded_at"] = "2026-10-25T11:01:00Z"
    assert tampered["content_sha256"] == original_hash
    path.write_text(json.dumps(tampered) + "\n")
    loaded = load_snapshots("cfb", 999999, root=tmp_path)
    assert pre_start(loaded, "2026-10-25T12:00:00Z") == []
