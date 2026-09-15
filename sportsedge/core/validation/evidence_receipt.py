"""Deterministic byte-level receipts for SportsEdge evidence bundles.

Receipts bind named files and immutable metadata into a canonical SHA-256 identity.
They establish provenance/reproducibility only; they confer no Model_P, promotion,
Truth Gate, staking, or OFFICIAL authority.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

SCHEMA = "SPORTSEDGE_EVIDENCE_RECEIPT_V1"


class EvidenceReceiptError(ValueError):
    """Raised when a receipt cannot be built safely."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _logical_path(value: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    path = PurePosixPath(text)
    if not text or path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise EvidenceReceiptError(f"unsafe logical path: {value!r}")
    return path.as_posix()


def build_evidence_receipt(
    files: Iterable[tuple[str, Path]],
    *,
    sport: str,
    purpose: str,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic receipt from exact file bytes and stable metadata."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for logical_name, file_path in files:
        logical = _logical_path(logical_name)
        if logical in seen:
            raise EvidenceReceiptError(f"duplicate logical path: {logical}")
        seen.add(logical)
        path = Path(file_path)
        raw = path.read_bytes()
        rows.append({
            "path": logical,
            "bytes": len(raw),
            "sha256": sha256(raw).hexdigest(),
        })
    rows.sort(key=lambda row: row["path"])
    payload = {
        "schema": SCHEMA,
        "sport": str(sport).lower(),
        "purpose": str(purpose),
        "files": rows,
        "metadata": dict(metadata or {}),
        "promotion_authority": False,
    }
    return {
        **payload,
        "receipt_sha256": sha256(canonical_json_bytes(payload)).hexdigest(),
    }


def verify_evidence_receipt(
    receipt: Mapping[str, Any],
    files: Mapping[str, Path],
) -> dict[str, Any]:
    """Verify an existing receipt against current bytes, fail-closed on drift."""
    differences: list[str] = []
    if receipt.get("schema") != SCHEMA:
        differences.append("SCHEMA_MISMATCH")

    expected_rows = receipt.get("files")
    if not isinstance(expected_rows, list):
        return {"status": "FAIL", "differences": ["FILES_INVALID"]}

    normalized: dict[str, Path] = {}
    try:
        for logical, path in files.items():
            safe = _logical_path(logical)
            if safe in normalized:
                raise EvidenceReceiptError(f"duplicate logical path: {safe}")
            normalized[safe] = Path(path)
    except EvidenceReceiptError:
        return {"status": "FAIL", "differences": ["INPUT_PATH_INVALID"]}

    expected_names = {str(row.get("path")) for row in expected_rows if isinstance(row, dict)}
    actual_names = set(normalized)
    for name in sorted(expected_names - actual_names):
        differences.append(f"MISSING:{name}")
    for name in sorted(actual_names - expected_names):
        differences.append(f"UNEXPECTED:{name}")

    for row in expected_rows:
        if not isinstance(row, dict):
            differences.append("FILE_ROW_INVALID")
            continue
        name = str(row.get("path") or "")
        path = normalized.get(name)
        if path is None:
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            differences.append(f"UNREADABLE:{name}")
            continue
        if len(raw) != row.get("bytes"):
            differences.append(f"SIZE_MISMATCH:{name}")
        if sha256(raw).hexdigest() != row.get("sha256"):
            differences.append(f"SHA256_MISMATCH:{name}")

    payload = {key: receipt.get(key) for key in (
        "schema", "sport", "purpose", "files", "metadata", "promotion_authority"
    )}
    digest = sha256(canonical_json_bytes(payload)).hexdigest()
    if digest != receipt.get("receipt_sha256"):
        differences.append("RECEIPT_SHA256_MISMATCH")

    return {
        "status": "PASS" if not differences else "FAIL",
        "differences": differences,
        "receipt_sha256": receipt.get("receipt_sha256"),
    }
