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
    PBP_PREDICTIVE_COLUMNS,
    PBP_PROJECTION_CONTRACT,
    PBP_SOURCE_TO_CANONICAL,
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


def _hex(value: Any, length: int, code: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != length or any(ch not in "0123456789abcdef" for ch in text):
        raise CFBParticipationPITError(code)
    return text


def _season(value: Any, code: str) -> int:
    if isinstance(value, bool):
        raise CFBParticipationPITError(code)
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise CFBParticipationPITError(code) from exc
    if out < 2000 or out > 2100:
        raise CFBParticipationPITError(code)
    return out


def _load_json(path: Path, code: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CFBParticipationPITError(code) from exc
    if not isinstance(payload, Mapping):
        raise CFBParticipationPITError(code)
    return dict(payload)


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _projection_blockers(
    *, dataset: str, projection: Any, source_root: Path, content_sha: str
) -> list[str]:
    blockers: list[str] = []
    if dataset != "play_by_play":
        if projection is not None:
            blockers.append(f"CFB_PARTICIPATION_UNEXPECTED_PROJECTION:{dataset}")
        return blockers
    if not isinstance(projection, Mapping):
        return ["CFB_PARTICIPATION_PBP_PROJECTION_REQUIRED"]
    if projection.get("contract") != PBP_PROJECTION_CONTRACT:
        blockers.append("CFB_PARTICIPATION_PBP_PROJECTION_CONTRACT_INVALID")
    if projection.get("raw_market_data_present") is not True:
        blockers.append("CFB_PARTICIPATION_PBP_RAW_MARKET_FLAG_REQUIRED")
    if projection.get("market_data_in_projection") is not False:
        blockers.append("CFB_PARTICIPATION_PBP_PROJECTION_MARKET_CONTAMINATION")
    if projection.get("raw_predictive_input_allowed") is not False:
        blockers.append("CFB_PARTICIPATION_PBP_RAW_PREDICTIVE_INPUT_FORBIDDEN")
    if projection.get("projection_predictive_input_allowed") is not True:
        blockers.append("CFB_PARTICIPATION_PBP_PROJECTION_NOT_AUTHORIZED")
    if projection.get("model_p_created") is not False or projection.get("promotion_authority") is not False:
        blockers.append("CFB_PARTICIPATION_PBP_PROJECTION_AUTHORITY_FORBIDDEN")
    if str(projection.get("source_content_sha256") or "").lower() != content_sha:
        blockers.append("CFB_PARTICIPATION_PBP_PROJECTION_SOURCE_SHA_MISMATCH")
    if list(projection.get("source_fields") or []) != list(PBP_SOURCE_TO_CANONICAL):
        blockers.append("CFB_PARTICIPATION_PBP_PROJECTION_SOURCE_ALLOWLIST_INVALID")
    if list(projection.get("predictive_columns") or []) != list(PBP_PREDICTIVE_COLUMNS):
        blockers.append("CFB_PARTICIPATION_PBP_PROJECTION_COLUMNS_INVALID")
    try:
        projection_sha = _hex(
            projection.get("projection_sha256"),
            64,
            "CFB_PARTICIPATION_PBP_PROJECTION_SHA_INVALID",
        )
        _hex(
            projection.get("sanitizer_code_sha256"),
            64,
            "CFB_PARTICIPATION_PBP_SANITIZER_SHA_INVALID",
        )
    except CFBParticipationPITError as exc:
        blockers.append(str(exc))
        projection_sha = None
    count = projection.get("projection_row_count")
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        blockers.append("CFB_PARTICIPATION_PBP_PROJECTION_ROW_COUNT_INVALID")
    rel = str(projection.get("projection_relative_path") or "").strip()
    if not rel:
        blockers.append("CFB_PARTICIPATION_PBP_PROJECTION_PATH_REQUIRED")
    else:
        projection_path = source_root / rel
        if not projection_path.is_file():
            blockers.append("CFB_PARTICIPATION_PBP_PROJECTION_FILE_MISSING")
        elif projection_sha is not None and _file_sha256(projection_path) != projection_sha:
            blockers.append("CFB_PARTICIPATION_PBP_PROJECTION_HASH_MISMATCH")
        else:
            try:
                header = projection_path.open("r", encoding="utf-8-sig").readline().rstrip("\r\n").split(",")
            except OSError:
                blockers.append("CFB_PARTICIPATION_PBP_PROJECTION_FILE_UNREADABLE")
            else:
                if header != list(PBP_PREDICTIVE_COLUMNS):
                    blockers.append("CFB_PARTICIPATION_PBP_PROJECTION_HEADER_INVALID")
    return blockers


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
    try:
        _hex(
            classification.get("capture_git_sha"),
            40,
            "CFB_PARTICIPATION_CAPTURE_GIT_SHA_INVALID",
        )
    except CFBParticipationPITError as exc:
        blockers.append(str(exc))
    try:
        capture_season = _season(
            classification.get("season"),
            "CFB_PARTICIPATION_CAPTURE_SEASON_INVALID",
        )
    except CFBParticipationPITError as exc:
        blockers.append(str(exc))
        capture_season = None
    if classification.get("point_in_time_from_capture_forward") is not True:
        blockers.append("CFB_PARTICIPATION_FORWARD_PIT_FLAG_MISSING")
    if classification.get("retroactive_point_in_time_claim") is not False:
        blockers.append("CFB_PARTICIPATION_RETROACTIVE_PIT_FORBIDDEN")
    if classification.get("market_data_in_predictive_capture") is not False:
        blockers.append("CFB_PARTICIPATION_MARKET_CONTAMINATION")
    if classification.get("participation_model_fit_performed") is not False:
        blockers.append("CFB_PARTICIPATION_CAPTURE_CANNOT_FIT_MODEL")
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
    declared_count = classification.get("asset_count")
    if isinstance(declared_count, bool) or not isinstance(declared_count, int) or declared_count != len(assets):
        blockers.append("CFB_PARTICIPATION_ASSET_COUNT_MISMATCH")

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
            row_season = _season(
                row.get("season"),
                f"CFB_PARTICIPATION_ASSET_SEASON_INVALID:{dataset}",
            )
            content_sha = _hex(
                row.get("content_sha256"),
                64,
                f"CFB_PARTICIPATION_CONTENT_SHA_INVALID:{dataset}",
            )
            declared_manifest_sha = _hex(
                row.get("manifest_sha256"),
                64,
                f"CFB_PARTICIPATION_MANIFEST_SHA_INVALID:{dataset}",
            )
            retrieved = _utc(
                row.get("source_retrieved_at"),
                f"CFB_PARTICIPATION_RETRIEVED_AT_INVALID:{dataset}",
            )
        except CFBParticipationPITError as exc:
            blockers.append(str(exc))
            continue
        if capture_season is not None and row_season != capture_season:
            blockers.append(f"CFB_PARTICIPATION_ASSET_SEASON_MISMATCH:{dataset}")
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
        if _file_sha256(cache_path) != content_sha:
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
        asset = manifest.get("asset")
        if not isinstance(asset, Mapping):
            blockers.append(f"CFB_PARTICIPATION_MANIFEST_ASSET_INVALID:{dataset}")
            continue
        if str(asset.get("dataset") or "").lower() != dataset:
            blockers.append(f"CFB_PARTICIPATION_MANIFEST_DATASET_MISMATCH:{dataset}")
            continue
        try:
            manifest_season = _season(
                asset.get("season"),
                f"CFB_PARTICIPATION_MANIFEST_SEASON_INVALID:{dataset}",
            )
            release_updated = _utc(
                asset.get("release_updated_at"),
                f"CFB_PARTICIPATION_RELEASE_UPDATED_AT_INVALID:{dataset}",
            )
            manifest_retrieved = _utc(
                manifest.get("retrieved_at"),
                f"CFB_PARTICIPATION_MANIFEST_RETRIEVED_AT_INVALID:{dataset}",
            )
        except CFBParticipationPITError as exc:
            blockers.append(str(exc))
            continue
        if manifest_season != row_season:
            blockers.append(f"CFB_PARTICIPATION_MANIFEST_SEASON_MISMATCH:{dataset}")
            continue
        if release_updated > manifest_retrieved:
            blockers.append(f"CFB_PARTICIPATION_RELEASE_UPDATE_AFTER_RETRIEVAL:{dataset}")
            continue
        if manifest_retrieved != retrieved:
            blockers.append(f"CFB_PARTICIPATION_RETRIEVAL_TIME_MISMATCH:{dataset}")
            continue
        if captured_at is not None and manifest_retrieved > captured_at:
            blockers.append(f"CFB_PARTICIPATION_MANIFEST_RETRIEVAL_AFTER_CAPTURE:{dataset}")
            continue
        if str(manifest.get("content_sha256") or "").lower() != content_sha:
            blockers.append(f"CFB_PARTICIPATION_MANIFEST_CONTENT_SHA_MISMATCH:{dataset}")
            continue
        if str(manifest.get("cache_relative_path") or "") != cache_rel:
            blockers.append(f"CFB_PARTICIPATION_MANIFEST_CACHE_PATH_MISMATCH:{dataset}")
            continue
        if str(asset.get("asset_name") or "") != str(row.get("asset_name") or ""):
            blockers.append(f"CFB_PARTICIPATION_ASSET_NAME_MISMATCH:{dataset}")
            continue
        identity_mismatch = False
        for field in ("release_tag", "release_id", "asset_id"):
            if asset.get(field) != row.get(field):
                blockers.append(f"CFB_PARTICIPATION_ASSET_IDENTITY_MISMATCH:{dataset}:{field}")
                identity_mismatch = True
                break
        if identity_mismatch:
            continue
        if manifest.get("contract") != PARTICIPATION_CAPTURE_CONTRACT:
            blockers.append(f"CFB_PARTICIPATION_MANIFEST_CONTRACT_INVALID:{dataset}")
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

        raw_market = manifest.get("raw_market_data_present")
        raw_allowed = manifest.get("raw_predictive_input_allowed")
        if row.get("raw_market_data_present") is not raw_market:
            blockers.append(f"CFB_PARTICIPATION_RAW_MARKET_FLAG_MISMATCH:{dataset}")
            continue
        if row.get("raw_predictive_input_allowed") is not raw_allowed:
            blockers.append(f"CFB_PARTICIPATION_RAW_PREDICTIVE_FLAG_MISMATCH:{dataset}")
            continue
        projection = manifest.get("predictive_projection")
        if row.get("predictive_projection") != projection:
            blockers.append(f"CFB_PARTICIPATION_PROJECTION_BINDING_MISMATCH:{dataset}")
            continue
        if dataset == "play_by_play":
            if raw_market is not True or raw_allowed is not False:
                blockers.append("CFB_PARTICIPATION_PBP_RAW_SOURCE_POLICY_INVALID")
                continue
        else:
            if raw_market is not False or raw_allowed is not True:
                blockers.append(f"CFB_PARTICIPATION_RAW_SOURCE_POLICY_INVALID:{dataset}")
                continue
        projection_errors = _projection_blockers(
            dataset=dataset,
            projection=projection,
            source_root=source_root,
            content_sha=content_sha,
        )
        if projection_errors:
            blockers.extend(projection_errors)
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
        "pbp_raw_market_data_present": True,
        "pbp_predictive_projection_required": True,
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
