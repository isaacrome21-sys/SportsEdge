"""Archive integrity: raw-first storage, append-only records, supersede chains."""

from sportsedge.participation.archive import ParticipationArchive, sha256_bytes
from sportsedge.participation.schema import (
    AVAIL_HISTORICAL,
    BASIS_FINAL_REPORT_RULE,
    SIGNAL_INJURY_DESIGNATION,
    TIMING_CADENCE,
    USE_PREGAME_FEATURE,
    ParticipationRecord,
)


def _rec(designation="Questionable", **kw):
    base = dict(
        signal_type=SIGNAL_INJURY_DESIGNATION, source_signal="S3", season=2026,
        week=5, team="BUF", captured_at_utc="2026-10-01T12:00:00Z",
        available_from_utc="2026-10-02T04:59:59Z",
        availability_class=AVAIL_HISTORICAL,
        availability_basis=BASIS_FINAL_REPORT_RULE, timing_evidence=TIMING_CADENCE,
        permitted_uses=[USE_PREGAME_FEATURE], source_name="test",
        gsis_id="00-0030000", payload={"designation": designation})
    base.update(kw)
    return ParticipationRecord(**base)


def test_raw_payload_stored_content_addressed(tmp_path):
    arc = ParticipationArchive(tmp_path)
    payload = b"a,b,c\n1,2,3\n"
    digest, ref = arc.store_raw_payload(payload)
    assert digest == sha256_bytes(payload)
    assert (tmp_path / ref).read_bytes() == payload
    # re-storing identical bytes is a no-op, not a rewrite
    digest2, ref2 = arc.store_raw_payload(payload)
    assert (digest2, ref2) == (digest, ref)


def test_append_only_and_supersede(tmp_path):
    arc = ParticipationArchive(tmp_path)
    first_id = arc.append_record(_rec("Questionable"))
    path = tmp_path / "records" / "INJURY_DESIGNATION.jsonl"
    bytes_after_first = path.read_bytes()

    second_id = arc.append_record(_rec("Out", supersedes_record_id=first_id))
    bytes_after_second = path.read_bytes()

    # the original bytes are an exact prefix: nothing was rewritten
    assert bytes_after_second.startswith(bytes_after_first)
    assert len(arc.load_records()) == 2
    current = arc.current_records()
    assert len(current) == 1
    assert current[0].record_id == second_id
    assert current[0].payload["designation"] == "Out"


def test_verify_integrity(tmp_path):
    arc = ParticipationArchive(tmp_path)
    arc.store_raw_payload(b"x,y\n1,2\n")
    arc.append_record(_rec())
    report = arc.verify_integrity()
    assert report["raw_payloads_verified"] == 1
    assert report["raw_payloads_hash_mismatch"] == []
    assert report["records_total"] == 1
    assert report["dangling_supersede_refs"] == []


def test_receipts_append(tmp_path):
    arc = ParticipationArchive(tmp_path)
    arc.append_receipt({"collector": "injuries", "season": 2023, "rows_in": 10})
    arc.append_receipt({"collector": "injuries", "season": 2024, "rows_in": 12})
    receipts = arc.load_receipts()
    assert [r["season"] for r in receipts] == [2023, 2024]
    assert all("receipt_id" in r for r in receipts)
