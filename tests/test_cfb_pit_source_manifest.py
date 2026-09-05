import json
from hashlib import sha256

import pytest

from sportsedge.sports.cfb.historical_features import CFB_HISTORICAL_MATERIALIZER_VERSION
from sportsedge.sports.cfb.joint_model import CFB_FEATURE_CONTRACT
from sportsedge.sports.cfb.source_manifest import (
    CFBSourceManifestError,
    CFB_PIT_SOURCE_MANIFEST_SCHEMA,
    validate_cfb_pit_source_manifest,
)


def _source(source_id: str, role: str, mode: str) -> dict:
    return {
        "source_id": source_id,
        "role": role,
        "provider": "fixture-provider",
        "dataset": f"fixture-{source_id}",
        "locator": f"fixtures/{source_id}.json",
        "retrieved_at_utc": "2026-09-05T18:00:00+00:00",
        "content_sha256": sha256(source_id.encode("utf-8")).hexdigest(),
        "availability_mode": mode,
        "availability_rule": "Only observations allowed by the declared role/cutoff are materialized.",
        "market_data": False,
        "post_cutoff_excluded": True,
        "seasons": [2024, 2025],
    }


def _manifest() -> dict:
    return {
        "schema_version": CFB_PIT_SOURCE_MANIFEST_SCHEMA,
        "generated_at_utc": "2026-09-05T18:00:00+00:00",
        "fit_max_season": 2025,
        "training_window": {"min_season": 2024, "max_season": 2025},
        "materializer_version": CFB_HISTORICAL_MATERIALIZER_VERSION,
        "feature_contract": CFB_FEATURE_CONTRACT,
        "post_cutoff_information_excluded": True,
        "market_data_used_as_model_feature": False,
        "sources": [
            _source("features", "FEATURE_INPUT", "EVENT_TIMESTAMPED_REPLAY"),
            _source("labels", "LABEL", "POST_EVENT_LABEL"),
        ],
    }


def _raw(payload: dict) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def test_valid_manifest_binds_exact_bytes() -> None:
    payload = _manifest()
    raw = _raw(payload)
    validated = validate_cfb_pit_source_manifest(payload, raw_bytes=raw, fit_max_season=2025)
    assert validated["manifest_sha256"] == sha256(raw).hexdigest()
    assert validated["source_count"] == 2
    assert validated["source_ids"] == ["features", "labels"]


def test_market_data_is_forbidden_for_every_training_source() -> None:
    payload = _manifest()
    payload["sources"][0]["market_data"] = True
    with pytest.raises(CFBSourceManifestError, match="MARKET_DATA_FLAG_REQUIRED_FALSE"):
        validate_cfb_pit_source_manifest(payload, raw_bytes=_raw(payload), fit_max_season=2025)


def test_post_event_values_cannot_be_feature_inputs() -> None:
    payload = _manifest()
    payload["sources"][0]["availability_mode"] = "POST_EVENT_LABEL"
    with pytest.raises(CFBSourceManifestError, match="POST_EVENT_FEATURE_PROHIBITED"):
        validate_cfb_pit_source_manifest(payload, raw_bytes=_raw(payload), fit_max_season=2025)


def test_label_source_must_be_declared_post_event_label() -> None:
    payload = _manifest()
    payload["sources"][1]["availability_mode"] = "EVENT_TIMESTAMPED_REPLAY"
    with pytest.raises(CFBSourceManifestError, match="LABEL_MODE_INVALID"):
        validate_cfb_pit_source_manifest(payload, raw_bytes=_raw(payload), fit_max_season=2025)


def test_manifest_fit_max_must_match_build_cutoff() -> None:
    payload = _manifest()
    with pytest.raises(CFBSourceManifestError, match="FIT_MAX_SEASON_MISMATCH"):
        validate_cfb_pit_source_manifest(payload, raw_bytes=_raw(payload), fit_max_season=2024)


def test_each_source_must_explicitly_exclude_post_cutoff_data() -> None:
    payload = _manifest()
    payload["sources"][0]["post_cutoff_excluded"] = False
    with pytest.raises(CFBSourceManifestError, match="SOURCE_POST_CUTOFF_EXCLUSION_REQUIRED"):
        validate_cfb_pit_source_manifest(payload, raw_bytes=_raw(payload), fit_max_season=2025)
