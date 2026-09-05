import json
from hashlib import sha256
from pathlib import Path

import pytest

from sportsedge.sports.cfb.historical_features import CFB_HISTORICAL_MATERIALIZER_VERSION
from sportsedge.sports.cfb.joint_model import CFB_FEATURE_CONTRACT
from sportsedge.sports.cfb.source_manifest import CFB_PIT_SOURCE_MANIFEST_SCHEMA
from sportsedge.sports.cfb.training_artifact import (
    CFBTrainingArtifactError,
    CFB_PIT_TRAINING_BUNDLE_SCHEMA,
    build_cfb_artifact_from_pit_bundle,
)


def _raw(payload: dict) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _manifest() -> dict:
    def source(source_id: str, role: str, mode: str) -> dict:
        return {
            "source_id": source_id,
            "role": role,
            "provider": "fixture-provider",
            "dataset": source_id,
            "locator": f"fixture://{source_id}",
            "snapshot_path": f"{source_id}.json",
            "retrieved_at_utc": "2026-09-05T18:00:00+00:00",
            "content_sha256": sha256(source_id.encode()).hexdigest(),
            "availability_mode": mode,
            "availability_rule": "Fixture-only declared cutoff rule.",
            "market_data": False,
            "post_cutoff_excluded": True,
            "seasons": [2024, 2025],
        }

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
            source("features", "FEATURE_INPUT", "EVENT_TIMESTAMPED_REPLAY"),
            source("labels", "LABEL", "POST_EVENT_LABEL"),
        ],
    }


def _bundle(source_manifest_sha256: str) -> dict:
    rows = [
        {"game_id": f"g{i}", "season": 2024 if i < 10 else 2025}
        for i in range(20)
    ]
    return {
        "schema_version": CFB_PIT_TRAINING_BUNDLE_SCHEMA,
        "materializer_version": CFB_HISTORICAL_MATERIALIZER_VERSION,
        "generated_at_utc": "2026-09-05T18:00:00+00:00",
        "source_manifest_sha256": source_manifest_sha256,
        "rows": rows,
    }


def test_build_rejects_naked_or_wrong_manifest_hash(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest_raw = _raw(manifest)
    bundle = _bundle("0" * 64)
    bundle_raw = _raw(bundle)
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "features.json").write_bytes(b"features")
    (evidence / "labels.json").write_bytes(b"labels")

    with pytest.raises(CFBTrainingArtifactError, match="SOURCE_MANIFEST_SHA256_MISMATCH"):
        build_cfb_artifact_from_pit_bundle(
            bundle,
            raw_bytes=bundle_raw,
            source_manifest=manifest,
            source_manifest_raw_bytes=manifest_raw,
            source_evidence_root=evidence,
            repo_root=tmp_path,
            fit_max_season=2025,
        )


def test_builder_cli_requires_manifest_and_evidence_root() -> None:
    text = Path("scripts/build_cfb_model_artifact.py").read_text(encoding="utf-8")
    assert 'ap.add_argument("--source-manifest", type=Path, required=True)' in text
    assert 'ap.add_argument("--source-evidence-root", type=Path, required=True)' in text
    assert "source_manifest_raw_bytes=manifest_raw" in text
    assert "source_evidence_root=args.source_evidence_root" in text
