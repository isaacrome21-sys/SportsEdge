"""Fail-closed predictive code-surface binding for certified NFL prop artifacts."""
from __future__ import annotations

from hashlib import sha1, sha256
import json
from pathlib import Path
from typing import Any, Mapping


class NFLPropCodeSurfaceError(ValueError):
    pass


def _canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    return sha256(raw).hexdigest()


def _git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return sha1(header + data).hexdigest()


def verify_nfl_prop_code_surface(*, root: Path, registry: Mapping[str, Any], artifact: Mapping[str, Any]) -> dict[str, Any]:
    if str(registry.get("sport") or "").upper() != "NFL":
        raise NFLPropCodeSurfaceError("NFL_PROP_CODE_SURFACE_SPORT_MISMATCH")
    fit_sha = str(artifact.get("code_git_sha") or "").strip().lower()
    if len(fit_sha) != 40 or any(ch not in "0123456789abcdef" for ch in fit_sha):
        raise NFLPropCodeSurfaceError("NFL_PROP_CODE_SURFACE_FIT_SHA_INVALID")
    if str(registry.get("code_git_sha") or "").strip().lower() != fit_sha:
        raise NFLPropCodeSurfaceError("NFL_PROP_CODE_SURFACE_FREEZE_FIT_SHA_MISMATCH")
    rel = str(registry.get("code_surface_manifest_path") or "").strip()
    if not rel:
        raise NFLPropCodeSurfaceError("NFL_PROP_CODE_SURFACE_MANIFEST_PATH_REQUIRED")
    manifest_path = (root / rel).resolve()
    try:
        manifest_path.relative_to(root.resolve())
    except ValueError as exc:
        raise NFLPropCodeSurfaceError("NFL_PROP_CODE_SURFACE_MANIFEST_PATH_INVALID") from exc
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise NFLPropCodeSurfaceError("NFL_PROP_CODE_SURFACE_MANIFEST_INVALID") from exc
    if not isinstance(manifest, dict):
        raise NFLPropCodeSurfaceError("NFL_PROP_CODE_SURFACE_MANIFEST_INVALID")
    expected_manifest_sha = str(registry.get("code_surface_manifest_sha256") or "").strip().lower()
    actual_manifest_sha = _canonical_sha256(manifest)
    if expected_manifest_sha != actual_manifest_sha:
        raise NFLPropCodeSurfaceError("NFL_PROP_CODE_SURFACE_MANIFEST_SHA256_MISMATCH")
    if manifest.get("schema_version") != "NFL_PROP_CODE_SURFACE_V1":
        raise NFLPropCodeSurfaceError("NFL_PROP_CODE_SURFACE_SCHEMA_MISMATCH")
    if str(manifest.get("sport") or "").upper() != "NFL":
        raise NFLPropCodeSurfaceError("NFL_PROP_CODE_SURFACE_SPORT_MISMATCH")
    if str(manifest.get("fit_git_sha") or "").lower() != fit_sha:
        raise NFLPropCodeSurfaceError("NFL_PROP_CODE_SURFACE_FIT_SHA_MISMATCH")
    if str(manifest.get("artifact_sha256") or "").lower() != str(registry.get("artifact_sha256") or "").lower():
        raise NFLPropCodeSurfaceError("NFL_PROP_CODE_SURFACE_ARTIFACT_SHA_MISMATCH")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise NFLPropCodeSurfaceError("NFL_PROP_CODE_SURFACE_FILES_REQUIRED")
    checked: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in files:
        if not isinstance(row, dict):
            raise NFLPropCodeSurfaceError("NFL_PROP_CODE_SURFACE_FILE_ENTRY_INVALID")
        path = str(row.get("path") or "").strip()
        expected_blob = str(row.get("git_blob_sha1") or "").strip().lower()
        if not path or path in seen:
            raise NFLPropCodeSurfaceError("NFL_PROP_CODE_SURFACE_FILE_PATH_INVALID")
        seen.add(path)
        if len(expected_blob) != 40 or any(ch not in "0123456789abcdef" for ch in expected_blob):
            raise NFLPropCodeSurfaceError(f"NFL_PROP_CODE_SURFACE_BLOB_SHA_INVALID:{path}")
        absolute = (root / path).resolve()
        try:
            absolute.relative_to(root.resolve())
        except ValueError as exc:
            raise NFLPropCodeSurfaceError(f"NFL_PROP_CODE_SURFACE_FILE_PATH_INVALID:{path}") from exc
        if not absolute.is_file():
            raise NFLPropCodeSurfaceError(f"NFL_PROP_CODE_SURFACE_FILE_MISSING:{path}")
        actual_blob = _git_blob_sha(absolute.read_bytes())
        if actual_blob != expected_blob:
            raise NFLPropCodeSurfaceError(f"NFL_PROP_CODE_SURFACE_BLOB_MISMATCH:{path}")
        checked.append({"path": path, "git_blob_sha1": actual_blob})
    return {"status": "COMPATIBLE", "sport": "NFL", "fit_git_sha": fit_sha, "artifact_sha256": str(registry.get("artifact_sha256")), "manifest_sha256": actual_manifest_sha, "files_checked": len(checked), "promotion_authority": False}
