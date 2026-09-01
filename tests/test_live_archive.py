from datetime import datetime, timezone

from sportsedge.live_archive import LiveArchiveRecord, append_record, verify_archive


NOW = datetime(2026, 8, 30, 2, 0, tzinfo=timezone.utc)


def test_live_archive_append_and_verify(tmp_path):
    path = tmp_path / "live.jsonl"
    record = LiveArchiveRecord(
        event_id="game-1",
        sport="NFL",
        snapshot_id="snap-1",
        pit_cutoff=NOW,
        recorded_at=NOW,
        record_type="STATE",
        payload={"down": 1, "distance": 10},
    )
    digest = append_record(path, record)
    assert digest == record.record_hash
    count, failures = verify_archive(path)
    assert count == 1
    assert failures == ()
