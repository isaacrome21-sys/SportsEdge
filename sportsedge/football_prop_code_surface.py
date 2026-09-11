"""Fail-closed NFL prop code-surface compatibility verification.

A fitted artifact remains bound to the exact Git revision that produced it.  A
later checkout may use that artifact only when every file declared capable of
changing the artifact or its Model_P runtime is byte-identical to the fitted
revision.  Unrelated repository changes therefore do not invalidate frozen model
bytes, while any declared model-surface change fails closed.
"""
from __future__ import annotations

from hashlib import sha1, sha256
import json
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = "NFL_PROP_CODE_SURFACE_V1"
ROOT = Path(__file__).resolve().parents[1]


class NFLPropCodeSurfaceError(ValueError):
    pass


def canonical_sha256(value: Any) -> str:
    try:
        raw = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise NFLPropCodeSurfaceError("NFL_PROP_CODE_SURFACE_CANONICAL_JSON_INVALID") from exc
    return sha256(raw).hexdigest()


def _normalized_sha(value: Any, length: int, error: str) -> str:
    raw = str(value or "").strip().lower()
    if len(raw) != length or any(ch not in "0123456789abcdef" for ch in raw):
        raise NFLPropCodeSurfaceError(error)
    return raw


def _repo_relative(value: Any) -> Path:
    raw = str(value or "").strip().replace("\\", "/")
    candidate = Path(raw)
    if not raw or candidate.is_absolute() or raw.startswith("./") or "//" in raw:
        raise NFLPropCodeSurfaceError("NFL_PROP_CODE_SURFACE_PATH_INVALID")
    if any(part in {"", ".", ".."} for part in candidate.parts):
        raise NFLPropCodeSurfaceError("NFL_PROP_CODE_SURFACE_PATH_INVALID")
    return candidate


def _git_blob_sha(path: Path) -> str:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise NFLPropCodeSurfaceError(f"NFL_PROP_CODE_SURFACE_FILE_MISSING:{path}") from exc
    return sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()


def load_and_verify_nfl_prop_code_surface(
    manifest_path: Path,
    *,
    repo_root: Path = ROOT,
    expected_sha256: str | None = None,
    expected_fit_git_sha: str | None = None,
) -> dict[str, Any]:
    try:
        payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise NFLPropCodeSurfaceError("NFL_PROP_CODE_SURFACE_MANIFEST_INVALID") from exc
    if not isinstance(payload, Mapping):
        raise NFLPropCodeSurfaceError("NFL_PROP_CODE_SURFACE_MANIFEST_INVALID")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise NFLPropCodeSurfaceError("NFL_PROP_CODE_SURFACE_SCHEMA_INVALID")

    fit_git_sha = _normalized_sha(
        payload.get("fit_git_sha"), 40, "NFL_PROP_CODE_SURFACE_FIT_GIT_SHA_INVALID"
    )
    if expected_fit_git_sha is not None:
        expected_fit = _normalized_sha(
            expected_fit_git_sha, 40, "NFL_PROP_CODE_SURFACE_EXPECTED_FIT_GIT_SHA_INVALID"
        )
        if fit_git_sha != expected_fit:
            raise NFLPropCodeSurfaceError("NFL_PROP_CODE_SURFACE_FIT_GIT_SHA_MISMATCH")

    files = payload.get("files")
    if not isinstance(files, Mapping) or not files:
        raise NFLPropCodeSurfaceError("NFL_PROP_CODE_SURFACE_FILES_REQUIRED")

    manifest_sha = canonical_sha256(payload)
    if expected_sha256 is not None:
        expected_manifest = _normalized_sha(
            expected_sha256, 64, "NFL_PROP_CODE_SURFACE_EXPECTED_SHA256_INVALID"
        )
        if manifest_sha != expected_manifest:
            raise NFLPropCodeSurfaceError("NFL_PROP_CODE_SURFACE_MANIFEST_SHA256_MISMATCH")

    normalized_files: dict[str, str] = {}
    root = Path(repo_root).resolve()
    for raw_path, raw_blob_sha in sorted(files.items(), key=lambda item: str(item[0])):
        relative = _repo_relative(raw_path)
        blob_sha = _normalized_sha(
            raw_blob_sha, 40, "NFL_PROP_CODE_SURFACE_GIT_BLOB_SHA_INVALID"
        )
        full_path = (root / relative).resolve()
        try:
            full_path.relative_to(root)
        except ValueError as exc:
            raise NFLPropCodeSurfaceError("NFL_PROP_CODE_SURFACE_PATH_ESCAPE") from exc
        actual = _git_blob_sha(full_path)
        if actual != blob_sha:
            raise NFLPropCodeSurfaceError(f"NFL_PROP_CODE_SURFACE_MISMATCH:{relative.as_posix()}")
        normalized_files[relative.as_posix()] = blob_sha

    return {
        "schema_version": SCHEMA_VERSION,
        "fit_git_sha": fit_git_sha,
        "manifest_sha256": manifest_sha,
        "file_count": len(normalized_files),
        "files": normalized_files,
    }


def nfl_prop_runtime_code_status(
    current_git_sha: str,
    freeze: Mapping[str, Any],
    *,
    repo_root: Path = ROOT,
) -> dict[str, Any]:
    """Verify current checkout compatibility while preserving fit SHA provenance."""
    current = _normalized_sha(
        current_git_sha, 40, "NFL_PROP_CODE_SURFACE_RUNTIME_GIT_SHA_INVALID"
    )
    fit_git_sha = _normalized_sha(
        freeze.get("code_git_sha"), 40, "NFL_PROP_CODE_SURFACE_FREEZE_GIT_SHA_INVALID"
    )
    manifest_raw = str(freeze.get("code_surface_manifest_path") or "").strip()
    manifest_sha_raw = str(freeze.get("code_surface_sha256") or "").strip()

    if not manifest_raw and not manifest_sha_raw:
        if current != fit_git_sha:
            raise NFLPropCodeSurfaceError("NFL_PROP_CODE_SURFACE_LEGACY_GIT_SHA_MISMATCH")
        return {
            "mode": "LEGACY_EXACT_REPO_SHA",
            "fit_git_sha": fit_git_sha,
            "runtime_git_sha": current,
            "compatible": True,
        }
    if not manifest_raw or not manifest_sha_raw:
        raise NFLPropCodeSurfaceError("NFL_PROP_CODE_SURFACE_BINDING_INCOMPLETE")

    relative = _repo_relative(manifest_raw)
    manifest = (Path(repo_root).resolve() / relative).resolve()
    verified = load_and_verify_nfl_prop_code_surface(
        manifest,
        repo_root=repo_root,
        expected_sha256=manifest_sha_raw,
        expected_fit_git_sha=fit_git_sha,
    )
    return {
        "mode": SCHEMA_VERSION,
        "fit_git_sha": fit_git_sha,
        "runtime_git_sha": current,
        "compatible": True,
        "manifest_path": relative.as_posix(),
        "manifest_sha256": verified["manifest_sha256"],
        "file_count": verified["file_count"],
    }
