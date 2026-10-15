"""Synthetic result-availability binder tests; no authenticated timestamps."""
import hashlib
import json

import pytest

from sportsedge.mlb_result_availability_binder import bind_result_availability


def _inputs(tmp_path):
    export = tmp_path / "export.json"
    export.write_text(json.dumps({
        "schema": "MLB_HISTORICAL_INNING_EXPORT_V1",
        "observed_at": "2024-04-04T00:00:00Z",
        "games": [{"game_id": "42", "start_time": "2024-04-01T18:00:00Z",
                   "inning_runs": [0] * 9}],
    }))
    attestation = tmp_path / "attestation.json"
    evidence = {"schema": "MLB_RESULT_AVAILABILITY_ATTESTATIONS_V1",
                "export_sha256": hashlib.sha256(export.read_bytes()).hexdigest(),
                "results": [{"game_id": "42",
                             "result_available_at": "2024-04-01T22:00:00Z",
                             "source_url": "https://example.org/synthetic",
                             "source_sha256": "a" * 64}]}
    attestation.write_text(json.dumps(evidence))
    return export, attestation


def test_binds_timestamp_without_authenticity_claim(tmp_path):
    source, evidence = _inputs(tmp_path)
    result = bind_result_availability(source, evidence, tmp_path / "bound.json")
    assert result["games"][0]["result_available_at"] == "2024-04-01T22:00:00Z"
    assert result["availability_attestation_authenticity_verified"] is False
    assert result["play_authorized"] is False


def test_rejects_modified_export(tmp_path):
    source, evidence = _inputs(tmp_path)
    source.write_text(source.read_text() + " ")
    with pytest.raises(ValueError, match="EXPORT_HASH_MISMATCH"):
        bind_result_availability(source, evidence, tmp_path / "bound.json")


def test_rejects_result_before_start(tmp_path):
    source, evidence = _inputs(tmp_path)
    data = json.loads(evidence.read_text())
    data["results"][0]["result_available_at"] = "2024-04-01T17:00:00Z"
    evidence.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="INVALID_RESULT_AVAILABILITY"):
        bind_result_availability(source, evidence, tmp_path / "bound.json")


def test_rejects_existing_output(tmp_path):
    source, evidence = _inputs(tmp_path)
    with pytest.raises(FileExistsError, match="OUTPUT_ALREADY_EXISTS"):
        bind_result_availability(source, evidence, source)
