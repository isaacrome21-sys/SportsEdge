import json
from pathlib import Path

import pytest

from sportsedge.mlb_model_artifact import (
    MLBModelArtifactError,
    load_verified_mlb_model_artifact,
    mlb_model_artifact_sha256,
)


def test_checked_in_mlb_model_surface_verifies_and_is_deterministic():
    first = load_verified_mlb_model_artifact()
    second = load_verified_mlb_model_artifact()
    assert first == second
    assert len(first["model_artifact_sha256"]) == 64
    assert first["promotion_eligible_by_artifact_alone"] is False
    assert mlb_model_artifact_sha256() == first["model_artifact_sha256"]


def test_surface_mutation_fails_closed(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "config/mlb_model_surface_v1.json").read_text())
    for rel in manifest["files"]:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((root / rel).read_bytes())
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config/mlb_model_surface_v1.json").write_text(json.dumps(manifest))
    victim = tmp_path / sorted(manifest["files"])[0]
    victim.write_bytes(victim.read_bytes() + b"\n# mutation\n")
    with pytest.raises(MLBModelArtifactError, match="MLB_MODEL_ARTIFACT_SURFACE_MISMATCH"):
        load_verified_mlb_model_artifact(repo_root=tmp_path)
