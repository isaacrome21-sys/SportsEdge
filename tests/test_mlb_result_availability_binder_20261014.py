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
                             "source_path": "snapshot.json",
                             "source_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest()}]}
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


def test_rejects_duplicate_export_game_ids(tmp_path):
    source, evidence = _inputs(tmp_path)
    data = json.loads(source.read_text())
    data["games"].append(dict(data["games"][0]))
    source.write_text(json.dumps(data))
    att = json.loads(evidence.read_text())
    att["export_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    evidence.write_text(json.dumps(att))
    with pytest.raises(ValueError, match="DUPLICATE_EXPORT_GAME"):
        bind_result_availability(source, evidence, tmp_path / "bound.json")


def test_rejects_malformed_export_row(tmp_path):
    source, evidence = _inputs(tmp_path)
    data = json.loads(source.read_text())
    data["games"] = [None]
    source.write_text(json.dumps(data))
    att = json.loads(evidence.read_text())
    att["export_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    evidence.write_text(json.dumps(att))
    with pytest.raises(ValueError, match="INVALID_EXPORT_GAMES"):
        bind_result_availability(source, evidence, tmp_path / "bound.json")


def test_rejects_tampered_snapshot(tmp_path):
    source, evidence = _inputs(tmp_path)
    (tmp_path / "snapshot.json").write_text("changed")
    with pytest.raises(ValueError, match="ATTESTATION_SOURCE_HASH_MISMATCH"):
        bind_result_availability(source, evidence, tmp_path / "bound.json")


def test_rejects_missing_snapshot(tmp_path):
    source, evidence = _inputs(tmp_path)
    (tmp_path / "snapshot.json").unlink()
    with pytest.raises(ValueError, match="MISSING_ATTESTATION_SOURCE_SNAPSHOT"):
        bind_result_availability(source, evidence, tmp_path / "bound.json")


def test_rejects_source_path_traversal(tmp_path):
    source, evidence = _inputs(tmp_path)
    data = json.loads(evidence.read_text())
    data["results"][0]["source_path"] = "../snapshot.json"
    evidence.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="UNSAFE_ATTESTATION_SOURCE_PATH"):
        bind_result_availability(source, evidence, tmp_path / "bound.json")


def test_rejects_missing_game_identifier(tmp_path):
    source, evidence = _inputs(tmp_path)
    data = json.loads(source.read_text())
    data["games"][0].pop("game_id")
    source.write_text(json.dumps(data))
    att = json.loads(evidence.read_text())
    att["export_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    evidence.write_text(json.dumps(att))
    with pytest.raises(ValueError, match="INVALID_EXPORT_GAME_ID"):
        bind_result_availability(source, evidence, tmp_path / "bound.json")


def test_rejects_symlinked_snapshot(tmp_path):
    source, evidence = _inputs(tmp_path)
    original = tmp_path / "snapshot.json"
    target = tmp_path / "target.json"
    original.rename(target)
    original.symlink_to(target)
    with pytest.raises(ValueError, match="MISSING_ATTESTATION_SOURCE_SNAPSHOT"):
        bind_result_availability(source, evidence, tmp_path / "bound.json")
