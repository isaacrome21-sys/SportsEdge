"""Fail-closed artifact and predictive code-surface binding for football props."""
from __future__ import annotations

import base64
import gzip
from hashlib import sha1, sha256
import json
from pathlib import Path
from typing import Any, Mapping


class NFLPropCodeSurfaceError(ValueError):
    pass


class CFBPropCodeSurfaceError(ValueError):
    pass


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return sha256(_canonical_bytes(value)).hexdigest()


def _git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return sha1(header + data).hexdigest()


def _under_root(root: Path, rel: str, error: str, *, error_cls: type[ValueError] = NFLPropCodeSurfaceError) -> Path:
    path = (root / rel).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise error_cls(error) from exc
    return path


def load_nfl_prop_artifact_bundle(*, root: Path, bundle_path: Path) -> dict[str, Any]:
    try:
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise NFLPropCodeSurfaceError("NFL_PROP_ARTIFACT_BUNDLE_INVALID") from exc
    if not isinstance(bundle, dict) or bundle.get("schema_version") != "FOOTBALL_PROP_ARTIFACT_BUNDLE_V1":
        raise NFLPropCodeSurfaceError("NFL_PROP_ARTIFACT_BUNDLE_INVALID")
    if str(bundle.get("sport") or "").upper() != "NFL" or bundle.get("promotion_authority") is not False:
        raise NFLPropCodeSurfaceError("NFL_PROP_ARTIFACT_BUNDLE_GOVERNANCE_INVALID")
    if bundle.get("encoding") != "GZIP_BASE64_CONCAT_V1":
        raise NFLPropCodeSurfaceError("NFL_PROP_ARTIFACT_BUNDLE_ENCODING_INVALID")
    parts = bundle.get("parts")
    if not isinstance(parts, list) or not parts:
        raise NFLPropCodeSurfaceError("NFL_PROP_ARTIFACT_BUNDLE_PARTS_REQUIRED")
    encoded: list[str] = []
    seen: set[str] = set()
    for row in parts:
        if not isinstance(row, dict):
            raise NFLPropCodeSurfaceError("NFL_PROP_ARTIFACT_BUNDLE_PART_INVALID")
        rel = str(row.get("path") or "").strip()
        expected = str(row.get("text_sha256") or "").strip().lower()
        if not rel or rel in seen:
            raise NFLPropCodeSurfaceError("NFL_PROP_ARTIFACT_BUNDLE_PART_PATH_INVALID")
        seen.add(rel)
        path = _under_root(root, rel, "NFL_PROP_ARTIFACT_BUNDLE_PART_PATH_INVALID")
        try:
            text = path.read_text(encoding="ascii").strip()
        except Exception as exc:
            raise NFLPropCodeSurfaceError(f"NFL_PROP_ARTIFACT_BUNDLE_PART_MISSING:{rel}") from exc
        if sha256(text.encode("ascii")).hexdigest() != expected:
            raise NFLPropCodeSurfaceError(f"NFL_PROP_ARTIFACT_BUNDLE_PART_SHA256_MISMATCH:{rel}")
        encoded.append(text)
    try:
        compressed = base64.b64decode("".join(encoded), validate=True)
    except Exception as exc:
        raise NFLPropCodeSurfaceError("NFL_PROP_ARTIFACT_BUNDLE_BASE64_INVALID") from exc
    if sha256(compressed).hexdigest() != str(bundle.get("compressed_sha256") or "").lower():
        raise NFLPropCodeSurfaceError("NFL_PROP_ARTIFACT_BUNDLE_COMPRESSED_SHA256_MISMATCH")
    try:
        raw = gzip.decompress(compressed)
        artifact = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise NFLPropCodeSurfaceError("NFL_PROP_ARTIFACT_BUNDLE_PAYLOAD_INVALID") from exc
    if not isinstance(artifact, dict):
        raise NFLPropCodeSurfaceError("NFL_PROP_ARTIFACT_BUNDLE_PAYLOAD_INVALID")
    expected_canonical = str(bundle.get("artifact_canonical_sha256") or "").lower()
    if _canonical_sha256(artifact) != expected_canonical:
        raise NFLPropCodeSurfaceError("NFL_PROP_ARTIFACT_BUNDLE_CANONICAL_SHA256_MISMATCH")
    return artifact


def _verify_prop_code_surface(
    *, root: Path, registry: Mapping[str, Any], artifact: Mapping[str, Any],
    sport: str, schema_version: str, error_cls: type[ValueError],
) -> dict[str, Any]:
    prefix = f"{sport}_PROP_CODE_SURFACE"
    if str(registry.get("sport") or "").upper() != sport:
        raise error_cls(f"{prefix}_SPORT_MISMATCH")
    fit_sha = str(artifact.get("code_git_sha") or "").strip().lower()
    if len(fit_sha) != 40 or any(ch not in "0123456789abcdef" for ch in fit_sha):
        raise error_cls(f"{prefix}_FIT_SHA_INVALID")
    if str(registry.get("code_git_sha") or "").strip().lower() != fit_sha:
        raise error_cls(f"{prefix}_FREEZE_FIT_SHA_MISMATCH")
    rel = str(registry.get("code_surface_manifest_path") or "").strip()
    if not rel:
        raise error_cls(f"{prefix}_MANIFEST_PATH_REQUIRED")
    manifest_path = _under_root(root, rel, f"{prefix}_MANIFEST_PATH_INVALID", error_cls=error_cls)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise error_cls(f"{prefix}_MANIFEST_INVALID") from exc
    if not isinstance(manifest, dict):
        raise error_cls(f"{prefix}_MANIFEST_INVALID")
    expected_manifest_sha = str(registry.get("code_surface_manifest_sha256") or "").strip().lower()
    actual_manifest_sha = _canonical_sha256(manifest)
    if expected_manifest_sha != actual_manifest_sha:
        raise error_cls(f"{prefix}_MANIFEST_SHA256_MISMATCH")
    if manifest.get("schema_version") != schema_version:
        raise error_cls(f"{prefix}_SCHEMA_MISMATCH")
    if str(manifest.get("sport") or "").upper() != sport:
        raise error_cls(f"{prefix}_SPORT_MISMATCH")
    if str(manifest.get("fit_git_sha") or "").lower() != fit_sha:
        raise error_cls(f"{prefix}_FIT_SHA_MISMATCH")
    if str(manifest.get("artifact_sha256") or "").lower() != str(registry.get("artifact_sha256") or "").lower():
        raise error_cls(f"{prefix}_ARTIFACT_SHA_MISMATCH")
    if manifest.get("promotion_authority") is not False:
        raise error_cls(f"{prefix}_PROMOTION_AUTHORITY_INVALID")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise error_cls(f"{prefix}_FILES_REQUIRED")
    checked: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in files:
        if not isinstance(row, dict):
            raise error_cls(f"{prefix}_FILE_ENTRY_INVALID")
        path = str(row.get("path") or "").strip()
        expected_blob = str(row.get("git_blob_sha1") or "").strip().lower()
        if not path or path in seen:
            raise error_cls(f"{prefix}_FILE_PATH_INVALID")
        seen.add(path)
        if len(expected_blob) != 40 or any(ch not in "0123456789abcdef" for ch in expected_blob):
            raise error_cls(f"{prefix}_BLOB_SHA_INVALID:{path}")
        absolute = _under_root(root, path, f"{prefix}_FILE_PATH_INVALID:{path}", error_cls=error_cls)
        if not absolute.is_file():
            raise error_cls(f"{prefix}_FILE_MISSING:{path}")
        actual_blob = _git_blob_sha(absolute.read_bytes())
        if actual_blob != expected_blob:
            raise error_cls(f"{prefix}_BLOB_MISMATCH:{path}")
        checked.append({"path": path, "git_blob_sha1": actual_blob})
    return {
        "status": "COMPATIBLE", "sport": sport, "fit_git_sha": fit_sha,
        "artifact_sha256": str(registry.get("artifact_sha256")),
        "manifest_sha256": actual_manifest_sha, "files_checked": len(checked),
        "promotion_authority": False,
    }


def verify_nfl_prop_code_surface(*, root: Path, registry: Mapping[str, Any], artifact: Mapping[str, Any]) -> dict[str, Any]:
    return _verify_prop_code_surface(
        root=root, registry=registry, artifact=artifact, sport="NFL",
        schema_version="NFL_PROP_CODE_SURFACE_V1", error_cls=NFLPropCodeSurfaceError,
    )


def verify_cfb_prop_code_surface(*, root: Path, registry: Mapping[str, Any], artifact: Mapping[str, Any]) -> dict[str, Any]:
    return _verify_prop_code_surface(
        root=root, registry=registry, artifact=artifact, sport="CFB",
        schema_version="CFB_PROP_CODE_SURFACE_V1", error_cls=CFBPropCodeSurfaceError,
    )
