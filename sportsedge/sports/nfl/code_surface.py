"""Byte-exact compatibility binding for a frozen NFL M2 artifact.

A fitted model is produced at one repository Git SHA. Unrelated repository-only
changes must not silently mutate that artifact's identity, but they also should
not invalidate it when every file that can affect M2 fitting/live inference is
byte-identical. This module verifies a frozen list of Git blob identities without
requiring a Git checkout or changing the artifact's original fit provenance.
"""
from __future__ import annotations

from hashlib import sha1, sha256
import json
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "NFL_M2_CODE_SURFACE_V1"


class NFLCodeSurfaceError(ValueError):
    pass


def _blob_sha(raw: bytes) -> str:
    header = f"blob {len(raw)}\0".encode("ascii")
    return sha1(header + raw).hexdigest()


def _canonical_sha(payload: Mapping[str, Any]) -> str:
    try:
        raw = json.dumps(
            dict(payload), sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise NFLCodeSurfaceError("NFL_M2_CODE_SURFACE_INVALID") from exc
    return sha256(raw).hexdigest()


def load_and_verify_nfl_m2_code_surface(
    path: str | Path,
    *,
    repo_root: str | Path,
    expected_sha256: str | None = None,
    expected_fit_git_sha: str | None = None,
) -> dict[str, Any]:
    target = Path(path)
    if not target.is_absolute():
        target = Path(repo_root) / target
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except Exception as exc:
        raise NFLCodeSurfaceError("NFL_M2_CODE_SURFACE_UNREADABLE") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA:
        raise NFLCodeSurfaceError("NFL_M2_CODE_SURFACE_SCHEMA_INVALID")
    fit_sha = str(payload.get("fit_git_sha") or "").strip().lower()
    if len(fit_sha) != 40 or any(ch not in "0123456789abcdef" for ch in fit_sha):
        raise NFLCodeSurfaceError("NFL_M2_CODE_SURFACE_FIT_GIT_SHA_INVALID")
    if expected_fit_git_sha is not None and fit_sha != str(expected_fit_git_sha).strip().lower():
        raise NFLCodeSurfaceError("NFL_M2_CODE_SURFACE_FIT_GIT_SHA_MISMATCH")
    files = payload.get("files")
    if not isinstance(files, dict) or not files:
        raise NFLCodeSurfaceError("NFL_M2_CODE_SURFACE_FILES_REQUIRED")
    root = Path(repo_root).resolve()
    for relative, expected_blob in sorted(files.items()):
        rel = Path(str(relative))
        if rel.is_absolute() or ".." in rel.parts:
            raise NFLCodeSurfaceError("NFL_M2_CODE_SURFACE_PATH_INVALID")
        expected = str(expected_blob or "").strip().lower()
        if len(expected) != 40 or any(ch not in "0123456789abcdef" for ch in expected):
            raise NFLCodeSurfaceError(f"NFL_M2_CODE_SURFACE_BLOB_INVALID:{relative}")
        source = (root / rel).resolve()
        try:
            source.relative_to(root)
        except ValueError as exc:
            raise NFLCodeSurfaceError("NFL_M2_CODE_SURFACE_PATH_ESCAPE") from exc
        if not source.is_file():
            raise NFLCodeSurfaceError(f"NFL_M2_CODE_SURFACE_FILE_MISSING:{relative}")
        actual = _blob_sha(source.read_bytes())
        if actual != expected:
            raise NFLCodeSurfaceError(f"NFL_M2_CODE_SURFACE_MISMATCH:{relative}")
    digest = _canonical_sha(payload)
    if expected_sha256 is not None and digest != str(expected_sha256).strip().lower():
        raise NFLCodeSurfaceError("NFL_M2_CODE_SURFACE_MANIFEST_SHA256_MISMATCH")
    return {
        "schema_version": SCHEMA,
        "fit_git_sha": fit_sha,
        "manifest_sha256": digest,
        "file_count": len(files),
    }
