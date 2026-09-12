"""Validate prospective CFB participation snapshots without granting model authority."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from .participation_source_capture import (
    PARTICIPATION_CAPTURE_CONTRACT,
    PARTICIPATION_DATASETS,
)

SNAPSHOT_SCHEMA = "CFB_FORWARD_PARTICIPATION_CAPTURE_V1"
REQUIRED_DATASETS = frozenset(PARTICIPATION_DATASETS)


class CFBParticipationPITError(ValueError):
    pass


def _utc(value: Any, code: str) -> datetime:
    raw = str(value or "").strip().replace("Z", "+00:00")
    if not raw:
        raise CFBParticipationPITError(code)
    try:
        out = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise CFBParticipationPITError(code) from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise CFBParticipationPITError(code)
    return out.astimezone(timezone.utc)


def _hex64(value: Any, code: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise CFBParticipationPITError(code)
    return text


def _load_json(path: Path, code: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CFBParticipationPITError(code) from exc
    if not isinstance(payload, Mapping):
        raise CFBParticipationPITError(code)
    return dict(payload)


def audit_cfb_participation_snapshot(
    classification_path: str | Path,
) -> dict[str, Any]:
    path = Path(classification_path)
    classification = _load_json(path, "CFB_PARTICIPATION_CLASSIFICATION_INVALID")
    blockers: list[str] = []
    if classification.get("schema_version") != SNAPSHOT_SCHEMA:
        blockers.append("CFB_PARTICIPATION_CLASSIFICATION_SCHEMA_INVALID")
    if str(classification.get("sport") or "").upper() != "CFB":
        blockers.append("CFB_PARTICIPATION_CLASSIFICATION_SPORT_INVALID")
    if classification.get("point_in_time_from_capture_forward") is not True:
        blockers.append("CFB_PARTICIPATION_FORWARD_PIT_FLAG_MISSING")
    if classification.get("retroactive_point_in_time_claim") is not False:
        blockers.append("CFB_PARTICIPATION_RETROACTIVE_PIT_FORBIDDEN")
    if classification.get("market_data_in_predictive_capture") is not False:
        blockers.append("CFB_PARTICIPATION_MARKET_CONTAMINATION")
    for field, code in (
        ("promotion_evidence", "CFB_PARTICIPATION_PROMOTION_AUTHORITY_FORBIDDEN"),
        ("model_p_created", "CFB_PARTICIPATION_MODEL_P_AUTHORITY_FORBIDDEN"),
        ("eligibility_changed", "CFB_PARTICIPATION_ELIGIBILITY_CHANGE_FORBIDDEN"),
    ):
        if classification.get(field) is not False:
            blockers.append(code)

    try:
        captured_at = _utc(
            classification.get("captured_at_utc"),
            "CFB_PARTICIPATION_CAPTURE_TIME_INVALID",
        )
    except CFBParticipationPITError as exc:
        blockers.append(str(exc))
        captured_at = None

    assets = classification.get("assets")
    if not isinstance(assets, list):
        blockers.append("CFB_PARTICIPATION_ASSETS_INVALID")
        assets = []
    datasets: list[str] = []
    verified_assets = 0
    source_root = path.parent.parent / "source"
    for row in assets:
        if not isinstance(row, Mapping):
            blockers.append("CFB_PARTICIPATION_ASSET_ROW_INVALID")
            continue
        dataset = str(row.get("dataset") or "").strip().lower()
        datasets.append(dataset)
        if dataset not in REQUIRED_DATASETS:
            blockers.append(f"CFB_PARTICIPATION_DATASET_UNEXPECTED:{dataset or 'MISSING'}")
            continue
        try:
            content_sha = _hex64(
                row.get("content_sha256"),
                f"CFB_PARTICIPATION_CONTENT_SHA_INVALID:{dataset}",
            )
            declared_manifest_sha = _hex64(
                row.get("manifest_sha256"),
                f"CFB_PARTICIPATION_MANIFEST_SHA_INVALID:{dataset}",
            )
            retrieved = _utc(
                row.get("source_retrieved_at"),
                f"CFB_PARTICIPATION_RETRIEVED_AT_INVALID:{dataset}",
            )
        except CFBParticipationPITError as exc:
            blockers.append(str(exc))
            continue
        if captured_at is not None and retrieved > captured_at:
            blockers.append(f"CFB_PARTICIPATION_RETRIEVAL_AFTER_CAPTURE:{dataset}")
            continue
        cache_rel = str(row.get("cache_relative_path") or "").strip()
        if not cache_rel:
            blockers.append(f"CFB_PARTICIPATION_CACHE_PATH_MISSING:{dataset}")
            continue
        cache_path = source_root / cache_rel
        manifest_path = cache_path.parent / "manifest.json"
        if not cache_path.is_file() or not manifest_path.is_file():
            blockers.append(f"CFB_PARTICIPATION_SOURCE_BYTES_MISSING:{dataset}")
            continue
        actual_content = sha256(cache_path.read_bytes()).hexdigest()
        if actual_content != content_sha:
            blockers.append(f"CFB_PARTICIPATION_CONTENT_HASH_MISMATCH:{dataset}")
            continue
        try:
            manifest = _load_json(
                manifest_path,
                f"CFB_PARTICIPATION_MANIFEST_INVALID:{dataset}",
            )
        except CFBParticipationPITError as exc:
            blockers.append(str(exc))
            continue
        embedded_sha = manifest.pop("manifest_sha256", None)
        actual_manifest_sha = sha256(
            json.dumps(
                manifest,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        if embedded_sha != declared_manifest_sha or actual_manifest_sha != declared_manifest_sha:
            blockers.append(f"CFB_PARTICIPATION_MANIFEST_HASH_MISMATCH:{dataset}")
            continue
        asset = manifest.get("asset") or {}
        if str(asset.get("dataset") or "").lower() != dataset:
            blockers.append(f"CFB_PARTICIPATION_MANIFEST_DATASET_MISMATCH:{dataset}")
            continue
        if manifest.get("contract") != PARTICIPATION_CAPTURE_CONTRACT:
            blockers.append(f"CFB_PARTICIPATION_MANIFEST_CONTRACT_INVALID:{dataset}")
            continue
        if manifest.get("market_data") is not False:
            blockers.append(f"CFB_PARTICIPATION_MARKET_DATA_FORBIDDEN:{dataset}")
            continue
        if manifest.get("point_in_time_from_retrieval_forward") is not True:
            blockers.append(f"CFB_PARTICIPATION_MANIFEST_FORWARD_PIT_MISSING:{dataset}")
            continue
        if manifest.get("retroactive_point_in_time_claim") is not False:
            blockers.append(f"CFB_PARTICIPATION_MANIFEST_RETROACTIVE_PIT_FORBIDDEN:{dataset}")
            continue
        if manifest.get("model_p_created") is not False or manifest.get("promotion_authority") is not False:
            blockers.append(f"CFB_PARTICIPATION_MANIFEST_AUTHORITY_FORBIDDEN:{dataset}")
            continue
        verified_assets += 1

    seen = set(datasets)
    missing = sorted(REQUIRED_DATASETS - seen)
    duplicates = sorted({name for name in seen if datasets.count(name) > 1})
    if missing:
        blockers.append("CFB_PARTICIPATION_DATASETS_MISSING:" + ",".join(missing))
    if duplicates:
        blockers.append("CFB_PARTICIPATION_DATASETS_DUPLICATE:" + ",".join(duplicates))
    ready = not blockers and verified_assets == len(REQUIRED_DATASETS)
    return {
        "schema_version": "CFB_PARTICIPATION_PIT_READINESS_V1",
        "sport": "CFB",
        "participation_source_asof_ready": ready,
        "verified_asset_count": verified_assets,
        "required_datasets": sorted(REQUIRED_DATASETS),
        "datasets_seen": sorted(seen),
        "blockers": blockers,
        "truth_gate_ready": False,
        "model_p_created": False,
        "promotion_authority": False,
        "eligibility_changed": False,
        "retroactive_point_in_time_claim": False,
    }


__all__ = [
    "CFBParticipationPITError",
    "REQUIRED_DATASETS",
    "SNAPSHOT_SCHEMA",
    "audit_cfb_participation_snapshot",
]
