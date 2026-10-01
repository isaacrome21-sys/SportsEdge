from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json

import pytest

from sportsedge.sports.nhl.prop_prediction_capture import (
    NHLPropPredictionCaptureError,
    append_receipts,
    receipts_from_source,
)


def _source(**overrides) -> bytes:
    row = {
        "market": "PLAYER_SHOTS",
        "game_id": "2026020001",
        "subject_id": "8478402",
        "line": 2.5,
        "candidate_p": 0.57,
        "baseline_p": 0.51,
        "baseline_kind": "MARKET_BLIND",
        "start_time_utc": "2026-10-08T23:00:00Z",
        "role_status": "CONFIRMED",
        "model_version": "nhl_shots_v1",
    }
    row.update(overrides)
    return json.dumps({"predictions": [row]}, separators=(",", ":")).encode("utf-8")


def _clock(hour: int = 22) -> datetime:
    return datetime(2026, 10, 8, hour, 0, tzinfo=timezone.utc)


def test_capture_stamps_wall_clock_and_hashes_exact_source_bytes():
    source = _source()
    receipt = receipts_from_source(source, captured_at=_clock())[0]

    assert receipt.captured_at == "2026-10-08T22:00:00Z"
    assert receipt.source_sha256 == hashlib.sha256(source).hexdigest()
    assert receipt.key == ("PLAYER_SHOTS", "2026020001", "8478402", 2.5)
    assert receipt.candidate_p == 0.57
    assert receipt.baseline_p == 0.51


def test_capture_rejects_non_market_blind_baseline():
    with pytest.raises(NHLPropPredictionCaptureError, match="MARKET_BLIND"):
        receipts_from_source(_source(baseline_kind="BOOK_IMPLIED"), captured_at=_clock())


@pytest.mark.parametrize("field,value", [("captured_at", "2026-10-01T00:00:00Z"), ("source_sha256", "0" * 64)])
def test_capture_rejects_caller_supplied_capture_owned_fields(field, value):
    with pytest.raises(NHLPropPredictionCaptureError, match="capture-owned"):
        receipts_from_source(_source(**{field: value}), captured_at=_clock())


def test_capture_rejects_post_puck_execution_instead_of_backfilling():
    with pytest.raises(NHLPropPredictionCaptureError, match="not pregame"):
        receipts_from_source(_source(), captured_at=_clock(hour=23))


def test_capture_reuses_frozen_line_grid_from_evaluator():
    with pytest.raises(NHLPropPredictionCaptureError, match="outside preregistered grid"):
        receipts_from_source(_source(line=2.0), captured_at=_clock())


def test_capture_rejects_duplicate_keys_inside_one_source_payload():
    row = json.loads(_source())["predictions"][0]
    source = json.dumps({"predictions": [row, dict(row)]}).encode("utf-8")
    with pytest.raises(NHLPropPredictionCaptureError, match="inside source payload"):
        receipts_from_source(source, captured_at=_clock())


def test_append_is_atomic_and_duplicate_key_leaves_existing_evidence_unchanged(tmp_path):
    output = tmp_path / "predictions.jsonl"
    receipts = receipts_from_source(_source(), captured_at=_clock())

    assert append_receipts(output, receipts) == 1
    before = output.read_bytes()

    with pytest.raises(NHLPropPredictionCaptureError, match="duplicate prediction key"):
        append_receipts(output, receipts)

    assert output.read_bytes() == before


def test_append_preserves_prior_bytes_and_adds_new_distinct_line(tmp_path):
    output = tmp_path / "predictions.jsonl"
    first = receipts_from_source(_source(), captured_at=_clock())
    append_receipts(output, first)
    prior = output.read_bytes()

    second_source = _source(subject_id="8478403", line=3.5, candidate_p=0.42)
    second = receipts_from_source(second_source, captured_at=_clock())
    append_receipts(output, second)

    combined = output.read_bytes()
    assert combined.startswith(prior)
    rows = [json.loads(line) for line in combined.decode("utf-8").splitlines()]
    assert len(rows) == 2
    assert rows[1]["subject_id"] == "8478403"
