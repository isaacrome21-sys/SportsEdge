import json
from hashlib import sha256
from pathlib import Path

import pytest

from sportsedge.sports.cfb.historical_features import CFB_HISTORICAL_MATERIALIZER_VERSION
from sportsedge.sports.cfb.joint_model import CFB_FEATURE_CONTRACT
from sportsedge.sports.cfb.source_manifest import (
    CFBSourceManifestError,
    CFB_PIT_SOURCE_MANIFEST_SCHEMA,
    validate_cfb_pit_source_manifest,
    verify_cfb_source_snapshots,
)


def _source(source_id: str, role: str, mode: str) -> dict:
    return {"source_id": source_id, "role": role, "provider": "fixture-provider", "dataset": f"fixture-{source_id}",
        "locator": f"fixture://{source_id}", "snapshot_path": f"{source_id}.json",
        "retrieved_at_utc": "2026-09-05T18:00:00+00:00", "content_sha256": sha256(source_id.encode()).hexdigest(),
        "availability_mode": mode, "availability_rule": "Declared role/cutoff only.", "market_data": False,
        "post_cutoff_excluded": True, "seasons": [2024, 2025]}


def _manifest() -> dict:
    return {"schema_version": CFB_PIT_SOURCE_MANIFEST_SCHEMA, "generated_at_utc": "2026-09-05T18:00:00+00:00",
        "fit_max_season": 2025, "training_window": {"min_season": 2024, "max_season": 2025},
        "materializer_version": CFB_HISTORICAL_MATERIALIZER_VERSION, "feature_contract": CFB_FEATURE_CONTRACT,
        "post_cutoff_information_excluded": True, "market_data_used_as_model_feature": False,
        "sources": [_source("features", "FEATURE_INPUT", "EVENT_TIMESTAMPED_REPLAY"), _source("labels", "LABEL", "POST_EVENT_LABEL")]}


def _raw(payload: dict) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def test_valid_manifest_binds_exact_bytes() -> None:
    payload = _manifest(); raw = _raw(payload)
    validated = validate_cfb_pit_source_manifest(payload, raw_bytes=raw, fit_max_season=2025)
    assert validated["manifest_sha256"] == sha256(raw).hexdigest()
    assert validated["source_ids"] == ["features", "labels"]


def test_market_data_and_post_event_features_are_forbidden() -> None:
    payload = _manifest(); payload["sources"][0]["market_data"] = True
    with pytest.raises(CFBSourceManifestError, match="MARKET_DATA_FLAG_REQUIRED_FALSE"):
        validate_cfb_pit_source_manifest(payload, raw_bytes=_raw(payload), fit_max_season=2025)
    payload = _manifest(); payload["sources"][0]["availability_mode"] = "POST_EVENT_LABEL"
    with pytest.raises(CFBSourceManifestError, match="POST_EVENT_FEATURE_PROHIBITED"):
        validate_cfb_pit_source_manifest(payload, raw_bytes=_raw(payload), fit_max_season=2025)


def test_preserved_snapshot_bytes_must_match_manifest_hashes(tmp_path: Path) -> None:
    payload = _manifest(); validated = validate_cfb_pit_source_manifest(payload, raw_bytes=_raw(payload), fit_max_season=2025)
    (tmp_path / "features.json").write_bytes(b"features"); (tmp_path / "labels.json").write_bytes(b"labels")
    assert verify_cfb_source_snapshots(validated, evidence_root=tmp_path)["verified_source_count"] == 2
    (tmp_path / "features.json").write_bytes(b"tampered")
    with pytest.raises(CFBSourceManifestError, match="SNAPSHOT_SHA256_MISMATCH:features"):
        verify_cfb_source_snapshots(validated, evidence_root=tmp_path)


def test_snapshot_path_cannot_escape_evidence_root() -> None:
    payload = _manifest(); payload["sources"][0]["snapshot_path"] = "../features.json"
    with pytest.raises(CFBSourceManifestError, match="SNAPSHOT_PATH_INVALID"):
        validate_cfb_pit_source_manifest(payload, raw_bytes=_raw(payload), fit_max_season=2025)
