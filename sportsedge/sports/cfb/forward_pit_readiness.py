"""Fail-closed validation for CFB forward-only source snapshots.

This is intentionally separate from historical PIT readiness.  A forward source
snapshot can prove source identity/as-of capture from its retrieval time onward;
it cannot prove historical point-in-time availability, paired market evidence,
Model_P, promotion, eligibility, staking, or OFFICIAL status.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

FORWARD_CLASSIFICATION = "FORWARD_SOURCE_SNAPSHOT_FROM_RETRIEVAL_TIME_ONLY"
_REQUIRED_DATASETS = {"adv_drives", "adv_situational", "adv_team", "schedules"}


class CFBForwardPITError(RuntimeError):
    """Raised when a forward snapshot is malformed or internally inconsistent."""


def _parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise CFBForwardPITError(f"{label}_MISSING")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CFBForwardPITError(f"{label}_INVALID") from exc


def _is_sha256(value: Any) -> bool:
    text = str(value or "").lower()
    return len(text) == 64 and all(ch in "0123456789abcdef" for ch in text)


def audit_cfb_forward_pit_snapshot(classification_path: Path) -> dict[str, Any]:
    """Validate one immutable forward snapshot classification, without promotion.

    The returned ``source_asof_ready`` means only that the classification proves
    an internally coherent forward-only source snapshot. ``truth_gate_ready`` is
    deliberately false unless separate future code supplies genuine paired
    market/outcome/promotion evidence; this validator has no authority to do so.
    """
    try:
        raw = classification_path.read_bytes()
        payload = json.loads(raw)
    except OSError as exc:
        raise CFBForwardPITError("CLASSIFICATION_READ_FAILED") from exc
    except Exception as exc:
        raise CFBForwardPITError("CLASSIFICATION_JSON_INVALID") from exc
    if not isinstance(payload, dict):
        raise CFBForwardPITError("CLASSIFICATION_OBJECT_REQUIRED")

    reasons: list[str] = []
    if payload.get("schema_version") != 1:
        reasons.append("SCHEMA_VERSION_INVALID")
    if str(payload.get("sport") or "").upper() != "CFB":
        reasons.append("SPORT_MISMATCH")
    if payload.get("pit_classification") != FORWARD_CLASSIFICATION:
        reasons.append("FORWARD_CLASSIFICATION_INVALID")
    if payload.get("point_in_time_from_capture_forward") is not True:
        reasons.append("FORWARD_PIT_ASSERTION_MISSING")
    if payload.get("retroactive_point_in_time_claim") is not False:
        reasons.append("RETROACTIVE_PIT_CLAIM_FORBIDDEN")
    if payload.get("promotion_evidence") is not False:
        reasons.append("PROMOTION_AUTHORITY_FORBIDDEN")
    if payload.get("model_p_created") is not False:
        reasons.append("MODEL_P_CREATION_FORBIDDEN")
    if payload.get("eligibility_changed") is not False:
        reasons.append("ELIGIBILITY_CHANGE_FORBIDDEN")

    try:
        captured_at = _parse_time(payload.get("captured_at_utc"), "CAPTURE_TIME")
    except CFBForwardPITError as exc:
        reasons.append(str(exc))
        captured_at = None

    assets = payload.get("assets")
    if not isinstance(assets, list) or not assets:
        reasons.append("ASSETS_MISSING")
        assets = []
    if payload.get("asset_count") != len(assets):
        reasons.append("ASSET_COUNT_MISMATCH")

    datasets: set[str] = set()
    asset_errors: list[str] = []
    for index, asset in enumerate(assets):
        if not isinstance(asset, dict):
            asset_errors.append(f"ASSET_{index}_INVALID")
            continue
        dataset = str(asset.get("dataset") or "")
        datasets.add(dataset)
        if not _is_sha256(asset.get("content_sha256")):
            asset_errors.append(f"{dataset or index}:CONTENT_SHA256_INVALID")
        if not _is_sha256(asset.get("manifest_sha256")):
            asset_errors.append(f"{dataset or index}:MANIFEST_SHA256_INVALID")
        try:
            retrieved = _parse_time(asset.get("source_retrieved_at"), "SOURCE_RETRIEVED_AT")
            if captured_at is not None and retrieved > captured_at:
                asset_errors.append(f"{dataset or index}:RETRIEVAL_AFTER_CAPTURE")
        except CFBForwardPITError as exc:
            asset_errors.append(f"{dataset or index}:{exc}")

    missing = sorted(_REQUIRED_DATASETS - datasets)
    if missing:
        reasons.append("REQUIRED_PREDICTIVE_SOURCES_MISSING")
    if asset_errors:
        reasons.append("SOURCE_BINDING_INVALID")

    source_asof_ready = not reasons
    market_present = payload.get("market_data_in_predictive_capture") is True
    blockers: list[str] = []
    if not source_asof_ready:
        blockers.append("FORWARD_SOURCE_SNAPSHOT_INVALID")
    if not market_present:
        blockers.append("PAIRED_MARKET_EVIDENCE_MISSING")
    # Even a future snapshot with market bytes cannot self-promote here. Separate
    # paired-decision/close validation and prospective outcome evidence are required.
    blockers.append("PROMOTION_EVIDENCE_NOT_ESTABLISHED")

    return {
        "contract": "SPORTSEDGE_CFB_FORWARD_PIT_READINESS_V1",
        "classification_sha256": sha256(raw).hexdigest(),
        "source_asof_ready": source_asof_ready,
        "forward_only": True,
        "retroactive_pit_allowed": False,
        "asset_count": len(assets),
        "datasets": sorted(datasets),
        "missing_required_datasets": missing,
        "asset_errors": asset_errors,
        "reasons": sorted(set(reasons)),
        "paired_market_evidence_present": market_present,
        "truth_gate_ready": False,
        "model_p_created": False,
        "promotion_authority": False,
        "eligibility_changed": False,
        "blockers": sorted(set(blockers)),
    }
