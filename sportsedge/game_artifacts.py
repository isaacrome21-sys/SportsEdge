"""Hash-verified runtime loading for canonical frozen MLB game artifacts."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

from .game_live_features import verify_artifact_feature_contract

GAME_SCORE_SHA256 = "49870123d7db6fca2f3b2985453c6aa3c685fb05da146c6c63601efd8623c272"
NRFI_SHA256 = "38c5ca528ffc0f6966e0b1d4be96f26a748467707b36865670cba421a20fe565"
GAME_SCORE_VERSION = "GAME_SCORE_V4_CUTOFF_CORRECT"
NRFI_VERSION = "NRFI_V4_CUTOFF_CORRECT"


class GameArtifactError(ValueError):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_one(path: str | Path, *, expected_sha256: str) -> Mapping[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise GameArtifactError(f"GAME_ARTIFACT_MISSING: {p}")
    got = _sha256(p)
    if got != expected_sha256:
        raise GameArtifactError(f"GAME_ARTIFACT_HASH_MISMATCH: {p.name}: {got}")
    try:
        import joblib
        value = joblib.load(p)
    except Exception as exc:
        raise GameArtifactError(f"GAME_ARTIFACT_LOAD_FAILED: {p.name}: {type(exc).__name__}") from exc
    if not isinstance(value, Mapping):
        raise GameArtifactError(f"GAME_ARTIFACT_NOT_MAPPING: {p.name}")
    return value


def load_frozen_game_artifacts(*, game_score_path: str | Path, nrfi_path: str | Path) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    """Load only the exact source-bounded/cutoff-correct v4 artifacts."""
    game = _load_one(game_score_path, expected_sha256=GAME_SCORE_SHA256)
    nrfi = _load_one(nrfi_path, expected_sha256=NRFI_SHA256)
    if str(game.get("version") or "") != GAME_SCORE_VERSION:
        raise GameArtifactError("GAME_SCORE_ARTIFACT_VERSION_MISMATCH")
    if str(nrfi.get("version") or "") != NRFI_VERSION:
        raise GameArtifactError("NRFI_ARTIFACT_VERSION_MISMATCH")
    verify_artifact_feature_contract(game, kind="run")
    verify_artifact_feature_contract(nrfi, kind="nrfi")
    return game, nrfi
