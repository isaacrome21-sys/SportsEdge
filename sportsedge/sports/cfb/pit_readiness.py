"""Fail-closed readiness audit for CFB historical promotion evidence.

This module does not create Model_P, change eligibility, or promote a market. It
only answers whether the historical evidence prerequisites declared by
CFB_TRUTH_GATE_V1 are present and hash-bound strongly enough to allow the real
holdout/Truth Gate execution to begin.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .source_manifest import (
    CFBSourceManifestError,
    validate_cfb_pit_source_manifest,
    verify_cfb_source_snapshots,
)

CFB_PIT_READINESS_CONTRACT = "SPORTSEDGE_CFB_PIT_READINESS_V1"
CFB_ASOF_AVAILABILITY_PROOF_CONTRACT = "SPORTSEDGE_CFB_ASOF_AVAILABILITY_PROOF_V1"
CFB_PAIRED_MARKET_EVIDENCE_CONTRACT = "SPORTSEDGE_CFB_PAIRED_MARKET_EVIDENCE_V1"
_REQUIRED_MARKETS = {"MONEYLINE", "SPREAD", "TOTAL"}


class CFBPITReadinessError(RuntimeError):
    """Raised when a supplied readiness artifact is malformed or unverifiable."""


def _sha256_bytes(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CFBPITReadinessError(f"READ_FAILED:{path}") from exc
    try:
        payload = json.loads(raw)
    except Exception as exc:
        raise CFBPITReadinessError(f"INVALID_JSON:{path}") from exc
    if not isinstance(payload, dict):
        raise CFBPITReadinessError(f"JSON_OBJECT_REQUIRED:{path}")
    return payload, raw


def _safe_path(root: Path, relative: Any, *, label: str) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise CFBPITReadinessError(f"{label}_PATH_INVALID")
    rel = PurePosixPath(relative.strip())
    if rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
        raise CFBPITReadinessError(f"{label}_PATH_INVALID:{relative}")
    root_resolved = root.resolve()
    candidate = (root_resolved / rel).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise CFBPITReadinessError(f"{label}_PATH_ESCAPES_ROOT:{relative}") from exc
    return candidate


def _verify_hash_bound_files(payload: Mapping[str, Any], *, root: Path, label: str) -> dict[str, Any]:
    rows = payload.get("evidence_files")
    result: dict[str, Any] = {"ready": False, "verified_file_count": 0, "reasons": []}
    if not isinstance(rows, list) or not rows:
        result["reasons"].append("HASH_BOUND_EVIDENCE_FILES_MISSING")
        return result

    errors: list[str] = []
    verified = 0
    for item in rows:
        if not isinstance(item, Mapping):
            errors.append("INVALID_EVIDENCE_ENTRY")
            continue
        relative = item.get("path")
        expected = str(item.get("sha256") or "").lower()
        try:
            path = _safe_path(root, relative, label=label)
        except CFBPITReadinessError as exc:
            errors.append(str(exc))
            continue
        if not path.is_file():
            errors.append(f"MISSING:{relative}")
            continue
        if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
            errors.append(f"SHA256_INVALID:{relative}")
            continue
        if _sha256_file(path) != expected:
            errors.append(f"SHA256_MISMATCH:{relative}")
            continue
        verified += 1

    result["verified_file_count"] = verified
    if errors:
        result["evidence_errors"] = errors
        result["reasons"].append("HASH_BOUND_EVIDENCE_VERIFICATION_FAILED")
    result["ready"] = not result["reasons"]
    return result


def _audit_current_release(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {"present": False, "usable_as_pit": False, "classification": None}
    payload, _ = _load_json(path)
    classification = payload.get("capture_classification")
    usable = (
        payload.get("point_in_time_as_of_game_proven") is True
        and payload.get("promotion_evidence") is True
    )
    return {
        "present": True,
        "usable_as_pit": usable,
        "classification": classification,
        "asset_count": payload.get("asset_count"),
        "point_in_time_as_of_game_proven": payload.get("point_in_time_as_of_game_proven") is True,
        "promotion_evidence": payload.get("promotion_evidence") is True,
        "sha256": _sha256_file(path),
    }


def _audit_pit_manifest(
    path: Path | None,
    *,
    evidence_root: Path | None,
) -> tuple[dict[str, Any], str | None]:
    if path is None or not path.is_file():
        return {"ready": False, "reasons": ["PIT_SOURCE_MANIFEST_MISSING"]}, None
    payload, raw = _load_json(path)
    manifest_sha = _sha256_bytes(raw)
    try:
        fit_max_season = int(payload.get("fit_max_season"))
        validated = validate_cfb_pit_source_manifest(
            payload,
            raw_bytes=raw,
            fit_max_season=fit_max_season,
        )
    except (TypeError, ValueError, CFBSourceManifestError) as exc:
        return {
            "ready": False,
            "reasons": ["PIT_SOURCE_MANIFEST_INVALID"],
            "error": str(exc),
            "sha256": manifest_sha,
        }, manifest_sha

    if evidence_root is None or not evidence_root.is_dir():
        return {
            "ready": False,
            "reasons": ["PIT_SOURCE_EVIDENCE_ROOT_MISSING"],
            "sha256": validated["manifest_sha256"],
            "source_count": validated["source_count"],
            "source_ids": validated["source_ids"],
            "training_window": validated["training_window"],
        }, validated["manifest_sha256"]

    try:
        verification = verify_cfb_source_snapshots(validated, evidence_root=evidence_root)
    except CFBSourceManifestError as exc:
        return {
            "ready": False,
            "reasons": ["PIT_SOURCE_SNAPSHOT_VERIFICATION_FAILED"],
            "error": str(exc),
            "sha256": validated["manifest_sha256"],
            "source_count": validated["source_count"],
            "source_ids": validated["source_ids"],
            "training_window": validated["training_window"],
        }, validated["manifest_sha256"]

    return {
        "ready": True,
        "reasons": [],
        "sha256": validated["manifest_sha256"],
        "source_count": validated["source_count"],
        "source_ids": validated["source_ids"],
        "training_window": validated["training_window"],
        "source_snapshot_verified": verification["source_snapshot_verified"],
        "source_content_root_sha256": verification["source_content_root_sha256"],
        "verified_source_count": verification["verified_source_count"],
    }, validated["manifest_sha256"]


def _audit_availability_proof(
    path: Path | None,
    *,
    source_manifest_sha256: str | None,
    evidence_root: Path | None,
) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {"ready": False, "reasons": ["ASOF_AVAILABILITY_PROOF_MISSING"]}
    payload, raw = _load_json(path)
    reasons: list[str] = []
    if payload.get("contract") != CFB_ASOF_AVAILABILITY_PROOF_CONTRACT:
        reasons.append("ASOF_AVAILABILITY_CONTRACT_INVALID")
    if payload.get("as_of_game_proven") is not True:
        reasons.append("ASOF_GAME_AVAILABILITY_NOT_PROVEN")
    if source_manifest_sha256 is None or payload.get("source_manifest_sha256") != source_manifest_sha256:
        reasons.append("SOURCE_MANIFEST_BINDING_MISMATCH")
    root = evidence_root if evidence_root is not None else path.parent
    file_check = _verify_hash_bound_files(payload, root=root, label="ASOF_EVIDENCE")
    reasons.extend(file_check["reasons"])
    return {
        "ready": not reasons,
        "reasons": sorted(set(reasons)),
        "sha256": _sha256_bytes(raw),
        "as_of_game_proven": payload.get("as_of_game_proven") is True,
        "verified_file_count": file_check["verified_file_count"],
        **({"evidence_errors": file_check["evidence_errors"]} if "evidence_errors" in file_check else {}),
    }


def _audit_market_evidence(path: Path | None, *, evidence_root: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {"ready": False, "reasons": ["PAIRED_MARKET_EVIDENCE_MISSING"]}
    payload, raw = _load_json(path)
    reasons: list[str] = []
    if payload.get("contract") != CFB_PAIRED_MARKET_EVIDENCE_CONTRACT:
        reasons.append("PAIRED_MARKET_EVIDENCE_CONTRACT_INVALID")
    if payload.get("paired_decision_close_prices_proven") is not True:
        reasons.append("PAIRED_DECISION_CLOSE_PRICES_NOT_PROVEN")
    if payload.get("decision_before_close_before_start") is not True:
        reasons.append("PRICE_TEMPORAL_ORDER_NOT_PROVEN")
    if payload.get("same_paired_price_row") is not True:
        reasons.append("SAME_PAIRED_PRICE_ROW_NOT_PROVEN")
    markets = payload.get("markets")
    if not isinstance(markets, list) or not _REQUIRED_MARKETS.issubset({str(v).upper() for v in markets}):
        reasons.append("REQUIRED_MARKETS_NOT_COVERED")
    root = evidence_root if evidence_root is not None else path.parent
    file_check = _verify_hash_bound_files(payload, root=root, label="MARKET_EVIDENCE")
    reasons.extend(file_check["reasons"])
    return {
        "ready": not reasons,
        "reasons": sorted(set(reasons)),
        "sha256": _sha256_bytes(raw),
        "markets": sorted({str(v).upper() for v in markets}) if isinstance(markets, list) else [],
        "verified_file_count": file_check["verified_file_count"],
        **({"evidence_errors": file_check["evidence_errors"]} if "evidence_errors" in file_check else {}),
    }


def audit_cfb_pit_readiness(
    *,
    truth_gate_path: Path,
    current_release_classification_path: Path | None = None,
    pit_source_manifest_path: Path | None = None,
    availability_proof_path: Path | None = None,
    paired_market_evidence_path: Path | None = None,
    evidence_root: Path | None = None,
) -> dict[str, Any]:
    truth_gate, _ = _load_json(truth_gate_path)
    if truth_gate.get("policy_id") != "CFB_TRUTH_GATE_V1":
        raise CFBPITReadinessError("CFB_TRUTH_GATE_POLICY_ID_MISMATCH")
    hard_gates = truth_gate.get("hard_gates")
    if not isinstance(hard_gates, Mapping):
        raise CFBPITReadinessError("CFB_TRUTH_GATE_HARD_GATES_MISSING")
    if hard_gates.get("pit_reproducibility_required") is not True:
        raise CFBPITReadinessError("CFB_TRUTH_GATE_PIT_REQUIREMENT_NOT_FROZEN_TRUE")
    if hard_gates.get("require_paired_historical_price_evidence") is not True:
        raise CFBPITReadinessError("CFB_TRUTH_GATE_PAIRED_PRICE_REQUIREMENT_NOT_FROZEN_TRUE")

    current_release = _audit_current_release(current_release_classification_path)
    manifest, manifest_sha = _audit_pit_manifest(
        pit_source_manifest_path,
        evidence_root=evidence_root,
    )
    availability = _audit_availability_proof(
        availability_proof_path,
        source_manifest_sha256=manifest_sha,
        evidence_root=evidence_root,
    )
    market = _audit_market_evidence(paired_market_evidence_path, evidence_root=evidence_root)

    blockers: list[str] = []
    if not manifest["ready"]:
        blockers.extend(manifest["reasons"])
    if not availability["ready"]:
        blockers.extend(availability["reasons"])
    if not market["ready"]:
        blockers.extend(market["reasons"])
    blockers = sorted(set(blockers))
    ready = not blockers

    return {
        "contract": CFB_PIT_READINESS_CONTRACT,
        "sport": "CFB",
        "truth_gate_policy_id": "CFB_TRUTH_GATE_V1",
        "truth_gate_sha256": _sha256_file(truth_gate_path),
        "readiness_state": "READY_FOR_REAL_HOLDOUT_EXECUTION" if ready else "BLOCKED_EVIDENCE_INCOMPLETE",
        "current_release": current_release,
        "pit_source_manifest": manifest,
        "asof_availability_proof": availability,
        "paired_market_evidence": market,
        "blockers": blockers,
        "historical_truth_gate_execution_allowed": ready,
        "forward_clock_allowed": ready,
        "promotion_authority": False,
        "model_p_created": False,
        "eligibility_changed": False,
    }


__all__ = [
    "CFB_PIT_READINESS_CONTRACT",
    "CFB_ASOF_AVAILABILITY_PROOF_CONTRACT",
    "CFB_PAIRED_MARKET_EVIDENCE_CONTRACT",
    "CFBPITReadinessError",
    "audit_cfb_pit_readiness",
]
