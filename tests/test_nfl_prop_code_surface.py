from __future__ import annotations

from hashlib import sha1, sha256
import json
from pathlib import Path

import pytest

from sportsedge.football_prop_run_machine import canonical_hash
from sportsedge.sports.nfl.prop_code_surface import (
    CFBPropCodeSurfaceError,
    NFLPropCodeSurfaceError,
    load_nfl_prop_artifact_bundle,
    verify_cfb_prop_code_surface,
    verify_nfl_prop_code_surface,
)

ROOT = Path(__file__).resolve().parents[1]
NFL_FREEZE = ROOT / "config/nfl_prop_model_freeze.json"
CFB_FREEZE = ROOT / "config/cfb_prop_model_freeze.json"
CERTIFIED_SHA = "3efa5cc92b5ed1bf53a99cbe0d6e7792d01791a77c8f684874d66213b73d9570"
FIT_SHA = "5dfa29347bed608771e6a2395ce8e894dbfdd881"
SOURCE_SHA = "71b6a1ed010e963dd0e8bb0b8a18d2a3a9cdef1914084631fe5adb9ed2c278da"
CFB_CERTIFIED_SHA = "923cfd1be42d31a87d9f31ddffce406d44bfc1bb003d1c625f5a4258f7773f23"
CFB_FIT_SHA = "67184a5a120a2bc868531c7827783f562f82ee0b"
CFB_SOURCE_SHA = "f25faa32ad8f1ddde16573a5919eeb108d267a04768a3b088d7db34b7682aa25"
CFB_CODE_SURFACE_SHA = "8abfd4b5ff1de138004e3f7b73bb0e5dcab123333e4f853ba4d427b1e808832e"


def _load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _artifact(freeze: dict) -> dict:
    return load_nfl_prop_artifact_bundle(root=ROOT, bundle_path=ROOT / freeze["artifact_path"])


def _canonical_sha(value: dict) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    return sha256(raw).hexdigest()


def _blob_sha(data: bytes) -> str:
    return sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def test_checked_in_nfl_artifact_is_exact_certified_bundle() -> None:
    freeze = _load(NFL_FREEZE)
    artifact = _artifact(freeze)
    assert freeze["status"] == "FROZEN"
    assert freeze["promotion_authority"] is False
    assert freeze["artifact_sha256"] == CERTIFIED_SHA
    assert freeze["code_git_sha"] == FIT_SHA
    assert freeze["source_manifest_sha256"] == SOURCE_SHA
    assert artifact["code_git_sha"] == FIT_SHA
    assert artifact["source_manifest_sha256"] == SOURCE_SHA
    assert canonical_hash(artifact) == CERTIFIED_SHA


def test_checked_in_nfl_predictive_surface_matches_certified_fit() -> None:
    freeze = _load(NFL_FREEZE)
    artifact = _artifact(freeze)
    result = verify_nfl_prop_code_surface(root=ROOT, registry=freeze, artifact=artifact)
    assert result["status"] == "COMPATIBLE"
    assert result["fit_git_sha"] == FIT_SHA
    assert result["artifact_sha256"] == CERTIFIED_SHA
    assert result["files_checked"] >= 10
    assert result["promotion_authority"] is False


def test_bundle_part_tamper_fails_closed(tmp_path: Path) -> None:
    freeze = _load(NFL_FREEZE)
    bundle_rel = freeze["artifact_path"]
    bundle = _load(ROOT / bundle_rel)
    bundle_dst = tmp_path / bundle_rel
    bundle_dst.parent.mkdir(parents=True, exist_ok=True)
    bundle_dst.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for row in bundle["parts"]:
        src = ROOT / row["path"]
        dst = tmp_path / row["path"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
    target = tmp_path / bundle["parts"][0]["path"]
    target.write_text(target.read_text(encoding="ascii") + "A", encoding="ascii")
    with pytest.raises(NFLPropCodeSurfaceError, match="NFL_PROP_ARTIFACT_BUNDLE_PART_SHA256_MISMATCH"):
        load_nfl_prop_artifact_bundle(root=tmp_path, bundle_path=bundle_dst)


def test_predictive_code_mutation_fails_closed(tmp_path: Path) -> None:
    freeze = _load(NFL_FREEZE)
    artifact = _artifact(freeze)
    manifest_rel = freeze["code_surface_manifest_path"]
    manifest = _load(ROOT / manifest_rel)
    for row in manifest["files"]:
        src = ROOT / row["path"]
        dst = tmp_path / row["path"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
    manifest_dst = tmp_path / manifest_rel
    manifest_dst.parent.mkdir(parents=True, exist_ok=True)
    manifest_dst.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    target = tmp_path / manifest["files"][0]["path"]
    target.write_bytes(target.read_bytes() + b"\n# predictive mutation\n")
    with pytest.raises(NFLPropCodeSurfaceError, match="NFL_PROP_CODE_SURFACE_BLOB_MISMATCH"):
        verify_nfl_prop_code_surface(root=tmp_path, registry=freeze, artifact=artifact)


def test_cfb_code_surface_can_attest_without_promoting(tmp_path: Path) -> None:
    predictive = tmp_path / "sportsedge/football_prop_run_machine.py"
    predictive.parent.mkdir(parents=True, exist_ok=True)
    predictive.write_text("# frozen predictive bytes\n", encoding="utf-8")
    artifact = {
        "code_git_sha": "4ce88ba49bef9ffd9de0709e775cf1edd92aec1a",
        "sport": "CFB",
    }
    artifact_sha = "55d6a1b3fc3443473f3733955e804cfcb94a5da478c21c25ecfd3771e20c6ed7"
    manifest = {
        "schema_version": "CFB_PROP_CODE_SURFACE_V1",
        "sport": "CFB",
        "fit_git_sha": artifact["code_git_sha"],
        "artifact_sha256": artifact_sha,
        "promotion_authority": False,
        "files": [{"path": "sportsedge/football_prop_run_machine.py", "git_blob_sha1": _blob_sha(predictive.read_bytes())}],
    }
    manifest_rel = "config/cfb_prop_code_surface_v1.json"
    manifest_path = tmp_path / manifest_rel
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    registry = {
        "sport": "CFB",
        "code_git_sha": artifact["code_git_sha"],
        "artifact_sha256": artifact_sha,
        "code_surface_manifest_path": manifest_rel,
        "code_surface_manifest_sha256": _canonical_sha(manifest),
    }
    result = verify_cfb_prop_code_surface(root=tmp_path, registry=registry, artifact=artifact)
    assert result["status"] == "COMPATIBLE"
    assert result["sport"] == "CFB"
    assert result["promotion_authority"] is False

    predictive.write_text("# mutated predictive bytes\n", encoding="utf-8")
    with pytest.raises(CFBPropCodeSurfaceError, match="CFB_PROP_CODE_SURFACE_BLOB_MISMATCH"):
        verify_cfb_prop_code_surface(root=tmp_path, registry=registry, artifact=artifact)


def test_cfb_prop_registry_is_bound_to_validated_artifact() -> None:
    freeze = _load(CFB_FREEZE)
    assert freeze["sport"] == "CFB"
    assert freeze["status"] == "FROZEN"
    assert freeze["artifact_sha256"] == CFB_CERTIFIED_SHA
    assert freeze["code_git_sha"] == CFB_FIT_SHA
    assert freeze["source_manifest_sha256"] == CFB_SOURCE_SHA
    assert freeze["code_surface_manifest_sha256"] == CFB_CODE_SURFACE_SHA
    assert freeze["promotion_authority"] is False
    assert (ROOT / freeze["artifact_path"]).is_file()
