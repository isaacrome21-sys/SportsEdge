"""Fail-closed validation for CFB forward-only source snapshots.

This is intentionally separate from historical PIT readiness. A forward source
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
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CFBForwardPITError(f"{label}_INVALID") from exc
    if parsed.tzinfo is None:
        raise CFBForwardPITError(f"{label}_TIMEZONE_MISSING")
    return parsed


def _is_sha256(value: Any) -> bool:
    text = str(value or "").lower()
    return len(text) == 64 and all(ch in "0123456789abcdef" for ch in text)


def _is_git_sha(value: Any) -> bool:
    text = str(value or "").lower()
    return len(text) == 40 and all(ch in "0123456789abcdef" for ch in text)


def _manifest_sha256(payload: dict[str, Any]) -> str:
    canonical = dict(payload)
    canonical.pop("manifest_sha256", None)
    raw = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return sha256(raw).hexdigest()


def _safe_cache_path(source_root: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    candidate = source_root / relative
    try:
        if not candidate.resolve().is_relative_to(source_root.resolve()):
            return None
    except OSError:
        return None
    return candidate


def audit_cfb_forward_pit_snapshot(classification_path: Path) -> dict[str, Any]:
    """Validate one immutable forward snapshot classification, without promotion.

    ``source_asof_ready`` means only that the classification and the persisted
    source bytes/manifests form one internally coherent forward-only snapshot.
    Paired market evidence is deliberately outside this predictive-source bundle,
    and this validator has no authority to create Model_P or promotion evidence.
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
    if payload.get("market_data_in_predictive_capture") is not False:
        reasons.append("PREDICTIVE_MARKET_CONTAMINATION_FORBIDDEN")
    if not _is_git_sha(payload.get("capture_git_sha")):
        reasons.append("CAPTURE_GIT_SHA_INVALID")

    season = payload.get("season")
    if not isinstance(season, int) or isinstance(season, bool) or not (2000 <= season <= 2100):
        reasons.append("SEASON_INVALID")

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

    source_root = classification_path.parent.parent / "source"
    if not source_root.is_dir():
        reasons.append("SOURCE_ROOT_MISSING")

    datasets: set[str] = set()
    asset_errors: list[str] = []
    for index, asset in enumerate(assets):
        if not isinstance(asset, dict):
            asset_errors.append(f"ASSET_{index}_INVALID")
            continue

        dataset = str(asset.get("dataset") or "")
        label = dataset or str(index)
        if dataset in datasets:
            asset_errors.append(f"{label}:DUPLICATE_DATASET")
        datasets.add(dataset)

        content_sha = str(asset.get("content_sha256") or "").lower()
        manifest_sha = str(asset.get("manifest_sha256") or "").lower()
        if not _is_sha256(content_sha):
            asset_errors.append(f"{label}:CONTENT_SHA256_INVALID")
        if not _is_sha256(manifest_sha):
            asset_errors.append(f"{label}:MANIFEST_SHA256_INVALID")

        try:
            retrieved = _parse_time(asset.get("source_retrieved_at"), "SOURCE_RETRIEVED_AT")
            if captured_at is not None and retrieved > captured_at:
                asset_errors.append(f"{label}:RETRIEVAL_AFTER_CAPTURE")
        except CFBForwardPITError as exc:
            asset_errors.append(f"{label}:{exc}")

        if asset.get("season") != season:
            asset_errors.append(f"{label}:SEASON_MISMATCH")

        cache_relative_path = asset.get("cache_relative_path")
        source_path = _safe_cache_path(source_root, cache_relative_path)
        if source_path is None:
            asset_errors.append(f"{label}:CACHE_PATH_INVALID")
            continue
        if not source_path.is_file():
            asset_errors.append(f"{label}:SOURCE_FILE_MISSING")
            continue

        try:
            actual_content_sha = sha256(source_path.read_bytes()).hexdigest()
        except OSError:
            asset_errors.append(f"{label}:SOURCE_FILE_READ_FAILED")
            continue
        if actual_content_sha != content_sha:
            asset_errors.append(f"{label}:CONTENT_SHA256_MISMATCH")

        manifest_path = source_path.parent / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except OSError:
            asset_errors.append(f"{label}:MANIFEST_MISSING_OR_UNREADABLE")
            continue
        except Exception:
            asset_errors.append(f"{label}:MANIFEST_JSON_INVALID")
            continue
        if not isinstance(manifest, dict):
            asset_errors.append(f"{label}:MANIFEST_OBJECT_REQUIRED")
            continue

        manifest_declared_sha = str(manifest.get("manifest_sha256") or "").lower()
        if manifest_declared_sha != manifest_sha:
            asset_errors.append(f"{label}:MANIFEST_SHA256_BINDING_MISMATCH")
        try:
            actual_manifest_sha = _manifest_sha256(manifest)
        except (TypeError, ValueError):
            asset_errors.append(f"{label}:MANIFEST_CANONICALIZATION_FAILED")
        else:
            if actual_manifest_sha != manifest_sha:
                asset_errors.append(f"{label}:MANIFEST_SHA256_MISMATCH")

        manifest_asset = manifest.get("asset")
        if not isinstance(manifest_asset, dict):
            asset_errors.append(f"{label}:MANIFEST_ASSET_MISSING")
            manifest_asset = {}

        if manifest.get("market_role") != "PREDICTIVE_INPUT":
            asset_errors.append(f"{label}:MANIFEST_MARKET_ROLE_INVALID")
        if manifest_asset.get("usage") != "PREDICTIVE_INPUT":
            asset_errors.append(f"{label}:MANIFEST_USAGE_INVALID")
        if manifest.get("cache_relative_path") != cache_relative_path:
            asset_errors.append(f"{label}:CACHE_PATH_BINDING_MISMATCH")
        if str(manifest.get("content_sha256") or "").lower() != content_sha:
            asset_errors.append(f"{label}:CONTENT_SHA256_BINDING_MISMATCH")
        if manifest.get("retrieved_at") != asset.get("source_retrieved_at"):
            asset_errors.append(f"{label}:RETRIEVAL_TIME_BINDING_MISMATCH")

        for field in ("dataset", "season", "release_tag", "release_id", "asset_id", "asset_name"):
            if manifest_asset.get(field) != asset.get(field):
                asset_errors.append(f"{label}:{field.upper()}_BINDING_MISMATCH")
        if str(manifest_asset.get("sha256") or "").lower() != content_sha:
            asset_errors.append(f"{label}:MANIFEST_ASSET_SHA256_MISMATCH")
        if source_path.name != str(asset.get("asset_name") or ""):
            asset_errors.append(f"{label}:ASSET_NAME_PATH_MISMATCH")

    missing = sorted(_REQUIRED_DATASETS - datasets)
    if missing:
        reasons.append("REQUIRED_PREDICTIVE_SOURCES_MISSING")
    if asset_errors:
        reasons.append("SOURCE_BINDING_INVALID")

    source_asof_ready = not reasons
    blockers: list[str] = []
    if not source_asof_ready:
        blockers.append("FORWARD_SOURCE_SNAPSHOT_INVALID")
    blockers.append("PAIRED_MARKET_EVIDENCE_MISSING")
    # A predictive-source snapshot never contains legitimate paired market evidence,
    # and it can never self-promote. Separate decision/close and outcome evidence is required.
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
        "paired_market_evidence_present": False,
        "truth_gate_ready": False,
        "model_p_created": False,
        "promotion_authority": False,
        "eligibility_changed": False,
        "blockers": sorted(set(blockers)),
    }
