from __future__ import annotations

import json
from pathlib import Path

import pytest

from sportsedge.football_prop_run_machine import canonical_hash
from sportsedge.sports.nfl.prop_code_surface import (
    NFLPropCodeSurfaceError,
    verify_nfl_prop_code_surface,
)


ROOT = Path(__file__).resolve().parents[1]
NFL_FREEZE = ROOT / "config/nfl_prop_model_freeze.json"
NFL_ARTIFACT = ROOT / "artifacts/football/nfl_offensive_prop_ab_model.json"
CFB_FREEZE = ROOT / "config/cfb_prop_model_freeze.json"
CERTIFIED_SHA = "3efa5cc92b5ed1bf53a99cbe0d6e7792d01791a77c8f684874d66213b73d9570"
FIT_SHA = "5dfa29347bed608771e6a2395ce8e894dbfdd881"
SOURCE_SHA = "71b6a1ed010e963dd0e8bb0b8a18d2a3a9cdef1914084631fe5adb9ed2c278da"


def _load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_checked_in_nfl_artifact_is_exact_certified_bundle() -> None:
    freeze = _load(NFL_FREEZE)
    artifact = _load(NFL_ARTIFACT)
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
    artifact = _load(NFL_ARTIFACT)
    result = verify_nfl_prop_code_surface(root=ROOT, registry=freeze, artifact=artifact)
    assert result["status"] == "COMPATIBLE"
    assert result["fit_git_sha"] == FIT_SHA
    assert result["artifact_sha256"] == CERTIFIED_SHA
    assert result["files_checked"] >= 10
    assert result["promotion_authority"] is False


def test_predictive_code_mutation_fails_closed(tmp_path: Path) -> None:
    freeze = _load(NFL_FREEZE)
    artifact = _load(NFL_ARTIFACT)
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


def test_cfb_prop_registry_remains_unfrozen() -> None:
    freeze = _load(CFB_FREEZE)
    assert freeze["sport"] == "CFB"
    assert freeze["status"] == "UNFROZEN"
    assert freeze["artifact_sha256"] is None
