import json

from sportsedge.mlb.nrfi_market_journal import append_jsonl, close_record, entry_record


def test_entry_and_close_records_are_append_only_and_not_promotion_evidence(tmp_path):
    path = tmp_path / "nrfi_market.jsonl"
    entry = entry_record(
        event_id="2026-08-21:PIT@LAD",
        side="NRFI",
        offered_american=-120,
        model_prob=0.58,
        consensus_prob=0.55,
        edge_prob=0.03,
        expected_value=0.0633333333,
        books_used=4,
        dispersion=0.018,
        captured_at_utc="2026-08-21T23:00:00+00:00",
    )
    close = close_record(
        event_id="2026-08-21:PIT@LAD",
        side="NRFI",
        entry_consensus_prob=0.55,
        closing_consensus_prob=0.57,
        closing_at_utc="2026-08-22T02:00:00+00:00",
    )
    append_jsonl(path, entry)
    append_jsonl(path, close)

    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [row["record_type"] for row in rows] == ["ENTRY", "CLOSE"]
    assert rows[0]["promotion_evidence"] is False
    assert rows[1]["promotion_evidence"] is False
    assert rows[1]["clv_probability_delta"] > 0
