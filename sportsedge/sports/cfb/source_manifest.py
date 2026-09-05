"""Strict source-manifest validation for frozen CFB training artifacts.

The manifest is evidence metadata, not a data fetcher.  Its exact bytes are hashed
and bound to the training bundle before a model may be fit.  Feature inputs must be
market-blind and must have an availability mode that can be replayed point in time.
Post-event values are allowed only when they are explicitly label sources.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from typing import Any, Mapping

from .historical_features import CFB_HISTORICAL_MATERIALIZER_VERSION
from .joint_model import CFB_FEATURE_CONTRACT

CFB_PIT_SOURCE_MANIFEST_SCHEMA = "CFB_PIT_SOURCE_MANIFEST_V1"

_ALLOWED_ROLES = {"FEATURE_INPUT", "LABEL", "UNIVERSE"}
_ALLOWED_AVAILABILITY_MODES = {
    "PRE_EVENT_ARCHIVE",
    "EVENT_TIMESTAMPED_REPLAY",
    "POST_EVENT_LABEL",
}


class CFBSourceManifestError(ValueError):
    pass


def _hex64(value: Any, error: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise CFBSourceManifestError(error)
    return text


def _text(value: Any, error: str) -> str:
    out = str(value or "").strip()
    if not out:
        raise CFBSourceManifestError(error)
    return out


def _aware_timestamp(value: Any, error: str) -> str:
    raw = str(value or "").strip().replace("Z", "+00:00")
    try:
        stamp = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise CFBSourceManifestError(error) from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise CFBSourceManifestError(error)
    return stamp.isoformat()


def validate_cfb_pit_source_manifest(
    payload: Mapping[str, Any],
    *,
    raw_bytes: bytes,
    fit_max_season: int,
) -> dict[str, Any]:
    """Validate and summarize the exact source manifest bound to a training build."""
    if not isinstance(payload, Mapping):
        raise CFBSourceManifestError("CFB_SOURCE_MANIFEST_MAPPING_REQUIRED")
    if payload.get("schema_version") != CFB_PIT_SOURCE_MANIFEST_SCHEMA:
        raise CFBSourceManifestError("CFB_SOURCE_MANIFEST_SCHEMA_INVALID")
    if payload.get("materializer_version") != CFB_HISTORICAL_MATERIALIZER_VERSION:
        raise CFBSourceManifestError("CFB_SOURCE_MANIFEST_MATERIALIZER_MISMATCH")
    if payload.get("feature_contract") != CFB_FEATURE_CONTRACT:
        raise CFBSourceManifestError("CFB_SOURCE_MANIFEST_FEATURE_CONTRACT_MISMATCH")

    try:
        manifest_fit_max = int(payload.get("fit_max_season"))
        expected_fit_max = int(fit_max_season)
    except (TypeError, ValueError) as exc:
        raise CFBSourceManifestError("CFB_SOURCE_MANIFEST_FIT_MAX_SEASON_INVALID") from exc
    if manifest_fit_max != expected_fit_max:
        raise CFBSourceManifestError("CFB_SOURCE_MANIFEST_FIT_MAX_SEASON_MISMATCH")

    _aware_timestamp(payload.get("generated_at_utc"), "CFB_SOURCE_MANIFEST_GENERATED_AT_INVALID")
    if payload.get("post_cutoff_information_excluded") is not True:
        raise CFBSourceManifestError("CFB_SOURCE_MANIFEST_POST_CUTOFF_EXCLUSION_REQUIRED")
    if payload.get("market_data_used_as_model_feature") is not False:
        raise CFBSourceManifestError("CFB_SOURCE_MANIFEST_MARKET_FEATURE_PROHIBITED")

    window = payload.get("training_window")
    if not isinstance(window, Mapping):
        raise CFBSourceManifestError("CFB_SOURCE_MANIFEST_TRAINING_WINDOW_REQUIRED")
    try:
        min_season = int(window.get("min_season"))
        max_season = int(window.get("max_season"))
    except (TypeError, ValueError) as exc:
        raise CFBSourceManifestError("CFB_SOURCE_MANIFEST_TRAINING_WINDOW_INVALID") from exc
    if min_season < 2000 or max_season != expected_fit_max or min_season > max_season:
        raise CFBSourceManifestError("CFB_SOURCE_MANIFEST_TRAINING_WINDOW_INVALID")

    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources or not all(isinstance(item, Mapping) for item in sources):
        raise CFBSourceManifestError("CFB_SOURCE_MANIFEST_SOURCES_REQUIRED")

    source_ids: set[str] = set()
    clean_sources: list[dict[str, Any]] = []
    roles_seen: set[str] = set()
    for index, item_raw in enumerate(sources):
        item = dict(item_raw)
        source_id = _text(item.get("source_id"), f"CFB_SOURCE_MANIFEST_SOURCE_ID_REQUIRED:{index}")
        if source_id in source_ids:
            raise CFBSourceManifestError(f"CFB_SOURCE_MANIFEST_SOURCE_ID_DUPLICATE:{source_id}")
        source_ids.add(source_id)
        role = _text(item.get("role"), f"CFB_SOURCE_MANIFEST_ROLE_REQUIRED:{source_id}").upper()
        if role not in _ALLOWED_ROLES:
            raise CFBSourceManifestError(f"CFB_SOURCE_MANIFEST_ROLE_INVALID:{source_id}")
        roles_seen.add(role)
        mode = _text(item.get("availability_mode"), f"CFB_SOURCE_MANIFEST_AVAILABILITY_MODE_REQUIRED:{source_id}").upper()
        if mode not in _ALLOWED_AVAILABILITY_MODES:
            raise CFBSourceManifestError(f"CFB_SOURCE_MANIFEST_AVAILABILITY_MODE_INVALID:{source_id}")
        if role == "FEATURE_INPUT" and mode == "POST_EVENT_LABEL":
            raise CFBSourceManifestError(f"CFB_SOURCE_MANIFEST_POST_EVENT_FEATURE_PROHIBITED:{source_id}")
        if role != "LABEL" and item.get("market_data") is not False:
            raise CFBSourceManifestError(f"CFB_SOURCE_MANIFEST_MARKET_DATA_FLAG_REQUIRED_FALSE:{source_id}")
        if role == "FEATURE_INPUT" and item.get("post_cutoff_excluded") is not True:
            raise CFBSourceManifestError(f"CFB_SOURCE_MANIFEST_SOURCE_POST_CUTOFF_EXCLUSION_REQUIRED:{source_id}")

        provider = _text(item.get("provider"), f"CFB_SOURCE_MANIFEST_PROVIDER_REQUIRED:{source_id}")
        dataset = _text(item.get("dataset"), f"CFB_SOURCE_MANIFEST_DATASET_REQUIRED:{source_id}")
        locator = _text(item.get("locator"), f"CFB_SOURCE_MANIFEST_LOCATOR_REQUIRED:{source_id}")
        retrieved_at = _aware_timestamp(
            item.get("retrieved_at_utc"),
            f"CFB_SOURCE_MANIFEST_RETRIEVED_AT_INVALID:{source_id}",
        )
        content_sha = _hex64(item.get("content_sha256"), f"CFB_SOURCE_MANIFEST_CONTENT_SHA256_INVALID:{source_id}")
        availability_rule = _text(
            item.get("availability_rule"),
            f"CFB_SOURCE_MANIFEST_AVAILABILITY_RULE_REQUIRED:{source_id}",
        )
        seasons = item.get("seasons")
        if not isinstance(seasons, list) or not seasons:
            raise CFBSourceManifestError(f"CFB_SOURCE_MANIFEST_SEASONS_REQUIRED:{source_id}")
        try:
            clean_seasons = sorted({int(season) for season in seasons})
        except (TypeError, ValueError) as exc:
            raise CFBSourceManifestError(f"CFB_SOURCE_MANIFEST_SEASONS_INVALID:{source_id}") from exc
        if clean_seasons[0] < min_season or clean_seasons[-1] > expected_fit_max:
            raise CFBSourceManifestError(f"CFB_SOURCE_MANIFEST_SEASON_OUT_OF_WINDOW:{source_id}")

        clean_sources.append({
            "source_id": source_id,
            "role": role,
            "provider": provider,
            "dataset": dataset,
            "locator": locator,
            "retrieved_at_utc": retrieved_at,
            "content_sha256": content_sha,
            "availability_mode": mode,
            "availability_rule": availability_rule,
            "market_data": bool(item.get("market_data")),
            "post_cutoff_excluded": item.get("post_cutoff_excluded") is True,
            "seasons": clean_seasons,
        })

    if "FEATURE_INPUT" not in roles_seen or "LABEL" not in roles_seen:
        raise CFBSourceManifestError("CFB_SOURCE_MANIFEST_FEATURE_AND_LABEL_SOURCES_REQUIRED")

    return {
        "schema_version": CFB_PIT_SOURCE_MANIFEST_SCHEMA,
        "manifest_sha256": sha256(raw_bytes).hexdigest(),
        "fit_max_season": expected_fit_max,
        "training_window": {"min_season": min_season, "max_season": max_season},
        "source_count": len(clean_sources),
        "source_ids": sorted(source_ids),
        "sources": clean_sources,
        "materializer_version": CFB_HISTORICAL_MATERIALIZER_VERSION,
        "feature_contract": CFB_FEATURE_CONTRACT,
    }


__all__ = [
    "CFB_PIT_SOURCE_MANIFEST_SCHEMA",
    "CFBSourceManifestError",
    "validate_cfb_pit_source_manifest",
]
