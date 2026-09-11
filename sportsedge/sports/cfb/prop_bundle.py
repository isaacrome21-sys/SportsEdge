"""Fail-closed loader for the checked-in CFB prop artifact bundle."""
from __future__ import annotations

import base64
import gzip
from hashlib import sha1, sha256
import json
from pathlib import Path
from typing import Any


class CFBPropBundleError(ValueError):
    pass


def _canonical_sha256(value: Any) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return sha256(raw).hexdigest()


def _git_blob_sha(data: bytes) -> str:
    return sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def _under_root(root: Path, rel: str) -> Path:
    path = (root / rel).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise CFBPropBundleError("CFB_PROP_ARTIFACT_BUNDLE_PART_PATH_INVALID") from exc
    return path


def load_cfb_prop_artifact_bundle(*, root: Path, bundle_path: Path) -> dict[str, Any]:
    try:
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CFBPropBundleError("CFB_PROP_ARTIFACT_BUNDLE_INVALID") from exc
    if not isinstance(bundle, dict) or bundle.get("schema_version") != "FOOTBALL_PROP_ARTIFACT_BUNDLE_V1":
        raise CFBPropBundleError("CFB_PROP_ARTIFACT_BUNDLE_INVALID")
    if str(bundle.get("sport") or "").upper() != "CFB" or bundle.get("promotion_authority") is not False:
        raise CFBPropBundleError("CFB_PROP_ARTIFACT_BUNDLE_GOVERNANCE_INVALID")
    if bundle.get("encoding") != "GZIP_BASE64_CONCAT_V1":
        raise CFBPropBundleError("CFB_PROP_ARTIFACT_BUNDLE_ENCODING_INVALID")

    parts = bundle.get("parts")
    if not isinstance(parts, list) or not parts:
        raise CFBPropBundleError("CFB_PROP_ARTIFACT_BUNDLE_PARTS_REQUIRED")
    encoded: list[str] = []
    seen: set[str] = set()
    for row in parts:
        if not isinstance(row, dict):
            raise CFBPropBundleError("CFB_PROP_ARTIFACT_BUNDLE_PART_INVALID")
        rel = str(row.get("path") or "").strip()
        expected_blob = str(row.get("git_blob_sha1") or "").strip().lower()
        if not rel or rel in seen:
            raise CFBPropBundleError("CFB_PROP_ARTIFACT_BUNDLE_PART_PATH_INVALID")
        if len(expected_blob) != 40 or any(ch not in "0123456789abcdef" for ch in expected_blob):
            raise CFBPropBundleError(f"CFB_PROP_ARTIFACT_BUNDLE_PART_BLOB_SHA_INVALID:{rel}")
        seen.add(rel)
        path = _under_root(root, rel)
        try:
            raw = path.read_bytes()
            text = raw.decode("ascii").strip()
        except Exception as exc:
            raise CFBPropBundleError(f"CFB_PROP_ARTIFACT_BUNDLE_PART_MISSING:{rel}") from exc
        if _git_blob_sha(raw) != expected_blob:
            raise CFBPropBundleError(f"CFB_PROP_ARTIFACT_BUNDLE_PART_BLOB_MISMATCH:{rel}")
        encoded.append(text)

    try:
        compressed = base64.b64decode("".join(encoded), validate=True)
    except Exception as exc:
        raise CFBPropBundleError("CFB_PROP_ARTIFACT_BUNDLE_BASE64_INVALID") from exc
    if sha256(compressed).hexdigest() != str(bundle.get("compressed_sha256") or "").lower():
        raise CFBPropBundleError("CFB_PROP_ARTIFACT_BUNDLE_COMPRESSED_SHA256_MISMATCH")

    try:
        artifact = json.loads(gzip.decompress(compressed).decode("utf-8"))
    except Exception as exc:
        raise CFBPropBundleError("CFB_PROP_ARTIFACT_BUNDLE_PAYLOAD_INVALID") from exc
    if not isinstance(artifact, dict):
        raise CFBPropBundleError("CFB_PROP_ARTIFACT_BUNDLE_PAYLOAD_INVALID")
    if artifact.get("schema_version") != "FOOTBALL_PROP_MODEL_ARTIFACT_V1" or str(artifact.get("sport") or "").upper() != "CFB":
        raise CFBPropBundleError("CFB_PROP_ARTIFACT_BUNDLE_PAYLOAD_GOVERNANCE_INVALID")
    expected_canonical = str(bundle.get("artifact_canonical_sha256") or "").lower()
    if _canonical_sha256(artifact) != expected_canonical:
        raise CFBPropBundleError("CFB_PROP_ARTIFACT_BUNDLE_CANONICAL_SHA256_MISMATCH")
    return artifact
