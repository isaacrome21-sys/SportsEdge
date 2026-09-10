"""PIT-bound construction of frozen CFB joint-model artifacts.

The runtime AUTO path never fits a model. This module is the only packaging
bridge from an already-materialized PIT training bundle to the hash-bound model
artifact consumed by AUTO. It does not fetch data or promote markets.

A build requires the training bundle, the exact source-manifest bytes whose
SHA-256 is declared by that bundle, and preserved source snapshots whose bytes
match every content hash declared by the manifest.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from math import isfinite
from pathlib import Path
from typing import Any, Mapping

from .historical_features import CFB_HISTORICAL_MATERIALIZER_VERSION
from .joint_model import fit_cfb_joint_score_model
from .model_artifact import build_cfb_model_artifact, cfb_model_code_surface_sha256
from .source_manifest import CFBSourceManifestError, validate_cfb_pit_source_manifest, verify_cfb_source_snapshots

CFB_PIT_TRAINING_BUNDLE_SCHEMA = "CFB_PIT_TRAINING_BUNDLE_V1"
CFB_TRAINING_CODE_SURFACE = (
    "sportsedge/sports/cfb/historical_features.py",
    "sportsedge/sports/cfb/training_artifact.py",
    "sportsedge/sports/cfb/source_manifest.py",
    "scripts/build_cfb_model_artifact.py",
)
CFB_TRAINING_SEED_POLICY = "NONE_DETERMINISTIC_RIDGE_V1"


class CFBTrainingArtifactError(ValueError):
    pass


def _hex64(value: Any, error: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise CFBTrainingArtifactError(error)
    return text


def _aware_timestamp(value: Any) -> str:
    raw = str(value or "").strip().replace("Z", "+00:00")
    try:
        stamp = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise CFBTrainingArtifactError("CFB_TRAINING_BUNDLE_GENERATED_AT_INVALID") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise CFBTrainingArtifactError("CFB_TRAINING_BUNDLE_GENERATED_AT_TIMEZONE_REQUIRED")
    return stamp.isoformat()


def _surface_sha256(repo_root: str | Path, paths: tuple[str, ...]) -> str:
    root = Path(repo_root).resolve(); digest = sha256()
    for relative in paths:
        path = root / relative
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise CFBTrainingArtifactError(f"CFB_TRAINING_CODE_SURFACE_UNREADABLE:{relative}") from exc
        digest.update(relative.encode("utf-8")); digest.update(b"\0"); digest.update(raw); digest.update(b"\0")
    return digest.hexdigest()


def cfb_training_code_surface_sha256(repo_root: str | Path) -> str:
    return _surface_sha256(repo_root, CFB_TRAINING_CODE_SURFACE)


def _game_ids_sha256(game_ids: list[str]) -> str:
    digest = sha256()
    for game_id in sorted(game_ids):
        digest.update(game_id.encode("utf-8")); digest.update(b"\0")
    return digest.hexdigest()


def validate_cfb_pit_training_bundle(payload: Mapping[str, Any], *, raw_bytes: bytes, fit_max_season: int) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise CFBTrainingArtifactError("CFB_TRAINING_BUNDLE_MAPPING_REQUIRED")
    if payload.get("schema_version") != CFB_PIT_TRAINING_BUNDLE_SCHEMA:
        raise CFBTrainingArtifactError("CFB_TRAINING_BUNDLE_SCHEMA_INVALID")
    if payload.get("materializer_version") != CFB_HISTORICAL_MATERIALIZER_VERSION:
        raise CFBTrainingArtifactError("CFB_TRAINING_BUNDLE_MATERIALIZER_MISMATCH")
    source_manifest_sha = _hex64(payload.get("source_manifest_sha256"), "CFB_TRAINING_SOURCE_MANIFEST_SHA256_INVALID")
    generated_at = _aware_timestamp(payload.get("generated_at_utc"))
    try:
        fit_max = int(fit_max_season)
    except (TypeError, ValueError) as exc:
        raise CFBTrainingArtifactError("CFB_TRAINING_FIT_MAX_SEASON_INVALID") from exc
    if fit_max < 2000 or fit_max > 2100:
        raise CFBTrainingArtifactError("CFB_TRAINING_FIT_MAX_SEASON_INVALID")
    rows = payload.get("rows")
    if not isinstance(rows, list) or len(rows) < 20 or not all(isinstance(row, Mapping) for row in rows):
        raise CFBTrainingArtifactError("CFB_TRAINING_ROWS_INSUFFICIENT_OR_INVALID")
    game_ids: set[str] = set(); seasons: set[int] = set(); clean_rows: list[dict[str, Any]] = []
    for index, raw in enumerate(rows):
        row = dict(raw); gid = str(row.get("game_id") or "").strip()
        if not gid:
            raise CFBTrainingArtifactError(f"CFB_TRAINING_GAME_ID_MISSING:{index}")
        if gid in game_ids:
            raise CFBTrainingArtifactError(f"CFB_TRAINING_GAME_DUPLICATE:{gid}")
        game_ids.add(gid)
        try:
            season = int(row.get("season"))
        except (TypeError, ValueError) as exc:
            raise CFBTrainingArtifactError(f"CFB_TRAINING_SEASON_INVALID:{gid}") from exc
        if season > fit_max:
            raise CFBTrainingArtifactError(f"CFB_TRAINING_FUTURE_SEASON_FORBIDDEN:{gid}:{season}")
        seasons.add(season); clean_rows.append(row)
    if max(seasons) != fit_max:
        raise CFBTrainingArtifactError("CFB_TRAINING_FIT_MAX_SEASON_NOT_REPRESENTED")
    return {"rows": clean_rows, "row_count": len(clean_rows), "game_ids_sha256": _game_ids_sha256(list(game_ids)),
        "train_seasons": sorted(seasons), "fit_max_season": fit_max, "generated_at_utc": generated_at,
        "source_manifest_sha256": source_manifest_sha, "training_bundle_sha256": sha256(raw_bytes).hexdigest(),
        "materializer_version": CFB_HISTORICAL_MATERIALIZER_VERSION}


def build_cfb_artifact_from_pit_bundle(
    payload: Mapping[str, Any], *, raw_bytes: bytes, source_manifest: Mapping[str, Any],
    source_manifest_raw_bytes: bytes, source_evidence_root: str | Path, repo_root: str | Path,
    fit_max_season: int, ridge_alpha: float = 10.0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    validated = validate_cfb_pit_training_bundle(payload, raw_bytes=raw_bytes, fit_max_season=fit_max_season)
    try:
        manifest = validate_cfb_pit_source_manifest(source_manifest, raw_bytes=source_manifest_raw_bytes, fit_max_season=fit_max_season)
        source_verification = verify_cfb_source_snapshots(manifest, evidence_root=source_evidence_root)
    except CFBSourceManifestError as exc:
        raise CFBTrainingArtifactError(str(exc)) from exc
    if manifest["manifest_sha256"] != validated["source_manifest_sha256"]:
        raise CFBTrainingArtifactError("CFB_TRAINING_SOURCE_MANIFEST_SHA256_MISMATCH")
    try:
        alpha = float(ridge_alpha)
    except (TypeError, ValueError) as exc:
        raise CFBTrainingArtifactError("CFB_TRAINING_RIDGE_ALPHA_INVALID") from exc
    if not isfinite(alpha) or alpha < 0:
        raise CFBTrainingArtifactError("CFB_TRAINING_RIDGE_ALPHA_INVALID")
    try:
        model = fit_cfb_joint_score_model(validated["rows"], ridge_alpha=alpha)
    except ValueError as exc:
        raise CFBTrainingArtifactError(str(exc)) from exc
    if tuple(model.train_seasons) != tuple(validated["train_seasons"]):
        raise CFBTrainingArtifactError("CFB_TRAINING_MODEL_SEASON_IDENTITY_MISMATCH")
    code_sha = cfb_model_code_surface_sha256(repo_root); training_code_sha = cfb_training_code_surface_sha256(repo_root)
    artifact = build_cfb_model_artifact(model, model_code_sha256=code_sha, training_source_sha256=validated["training_bundle_sha256"])
    provenance = {
        "schema_version": "CFB_MODEL_TRAINING_PROVENANCE_V1", "model_id": artifact["model_id"],
        "feature_contract": artifact["feature_contract"], "artifact_sha256": artifact["artifact_sha256"],
        "model_code_sha256": code_sha, "training_code_sha256": training_code_sha,
        "training_bundle_sha256": validated["training_bundle_sha256"],
        "upstream_source_manifest_sha256": manifest["manifest_sha256"], "source_manifest_schema": manifest["schema_version"],
        "source_count": manifest["source_count"], "source_ids": manifest["source_ids"],
        "source_snapshot_verified": source_verification["source_snapshot_verified"],
        "source_content_root_sha256": source_verification["source_content_root_sha256"],
        "verified_source_count": source_verification["verified_source_count"], "game_ids_sha256": validated["game_ids_sha256"],
        "materializer_version": validated["materializer_version"], "generated_at_utc": validated["generated_at_utc"],
        "fit_max_season": validated["fit_max_season"], "train_seasons": validated["train_seasons"],
        "training_window": manifest["training_window"], "row_count": validated["row_count"], "ridge_alpha": alpha,
        "training_seed_policy": CFB_TRAINING_SEED_POLICY, "promotion_changed": False,
    }
    return artifact, provenance


__all__ = ["CFB_PIT_TRAINING_BUNDLE_SCHEMA", "CFB_TRAINING_CODE_SURFACE", "CFB_TRAINING_SEED_POLICY",
    "CFBTrainingArtifactError", "build_cfb_artifact_from_pit_bundle", "cfb_training_code_surface_sha256",
    "validate_cfb_pit_training_bundle"]
