"""Canonical, deterministic receipts for evidence bundles.

The receipt is deliberately sport-neutral and authority-neutral.  It binds bytes
and caller-supplied immutable metadata into one SHA-256 identity; it does not
create Model_P, Truth Gate, promotion, staking, eligibility, or OFFICIAL
authority.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA = "SPORTSEDGE_EVIDENCE_RECEIPT_V1"


def canonical_json_bytes(value: Any) -> bytes:
    """Return a stable JSON encoding suitable for hashing."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _relative(root: Path, path: Path) -> str:
    root_resolved = root.resolve()
    path_resolved = path.resolve()
    if not path_resolved.is_relative_to(root_resolved):
        raise ValueError(f"path escapes root: {path}")
    return path_resolved.relative_to(root_resolved).as_posix()


def file_facts(root: Path, paths: Iterable[Path]) -> list[dict[str, Any]]:
    """Hash files deterministically, sorted by normalized root-relative path."""
    rows: list[dict[str, Any]] = []
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(path)
        rows.append(
            {
                "path": _relative(root, path),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return sorted(rows, key=lambda row: row["path"])


def build_receipt(
    *,
    lane: str,
    root: Path,
    inputs: Iterable[Path] = (),
    outputs: Iterable[Path] = (),
    policy_path: Path | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a timestamp-free receipt whose identity is reproducible byte-for-byte."""
    body: dict[str, Any] = {
        "schema": SCHEMA,
        "lane": str(lane),
        "inputs": file_facts(root, inputs),
        "outputs": file_facts(root, outputs),
        "metadata": dict(metadata or {}),
        "authority": {
            "model_p_created": False,
            "truth_gate_ready": False,
            "promotion_authority": False,
            "staking_authority": False,
            "eligibility_authority": False,
            "official_authority": False,
        },
    }
    if policy_path is not None:
        if not policy_path.is_file():
            raise FileNotFoundError(policy_path)
        body["policy"] = {
            "path": _relative(root, policy_path),
            "sha256": sha256_file(policy_path),
        }
    return {**body, "receipt_sha256": sha256_bytes(canonical_json_bytes(body))}


def verify_receipt(receipt: Mapping[str, Any], *, root: Path) -> list[str]:
    """Return deterministic verification errors.  Empty means byte bindings match."""
    errors: list[str] = []
    if receipt.get("schema") != SCHEMA:
        errors.append("SCHEMA_MISMATCH")

    expected_receipt_sha = str(receipt.get("receipt_sha256") or "")
    body = dict(receipt)
    body.pop("receipt_sha256", None)
    actual_receipt_sha = sha256_bytes(canonical_json_bytes(body))
    if expected_receipt_sha != actual_receipt_sha:
        errors.append("RECEIPT_SHA256_MISMATCH")

    for section in ("inputs", "outputs"):
        rows = receipt.get(section)
        if not isinstance(rows, list):
            errors.append(f"{section.upper()}_INVALID")
            continue
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                errors.append(f"{section.upper()}_{index}:ROW_INVALID")
                continue
            rel = row.get("path")
            if not isinstance(rel, str) or not rel:
                errors.append(f"{section.upper()}_{index}:PATH_INVALID")
                continue
            path = root / rel
            try:
                if not path.resolve().is_relative_to(root.resolve()):
                    errors.append(f"{section.upper()}_{index}:PATH_ESCAPES_ROOT")
                    continue
            except OSError:
                errors.append(f"{section.upper()}_{index}:PATH_INVALID")
                continue
            if not path.is_file():
                errors.append(f"{section.upper()}_{index}:FILE_MISSING")
                continue
            if path.stat().st_size != row.get("bytes"):
                errors.append(f"{section.upper()}_{index}:BYTE_COUNT_MISMATCH")
            if sha256_file(path) != row.get("sha256"):
                errors.append(f"{section.upper()}_{index}:SHA256_MISMATCH")

    policy = receipt.get("policy")
    if policy is not None:
        if not isinstance(policy, Mapping):
            errors.append("POLICY_INVALID")
        else:
            rel = policy.get("path")
            if not isinstance(rel, str) or not rel:
                errors.append("POLICY_PATH_INVALID")
            else:
                path = root / rel
                if not path.is_file():
                    errors.append("POLICY_FILE_MISSING")
                elif sha256_file(path) != policy.get("sha256"):
                    errors.append("POLICY_SHA256_MISMATCH")

    return sorted(set(errors))


def write_receipt(path: Path, receipt: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(receipt), indent=2, sort_keys=True) + "\n", encoding="utf-8")
