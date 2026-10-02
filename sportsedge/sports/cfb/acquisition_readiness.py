"""Fail-closed readiness gate for reconstructed CFB historical acquisition.

Supports both the legacy private quota manifest and the redacted public proof emitted
after a successful guarded materialization. The public proof never exposes account
quota values; it proves the same preflight decisions plus hash/timestamp provenance
for the acquired source cache.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
CFB_ACQUISITION_READINESS_VERSION = "CFB_ACQUISITION_READINESS_V2"
PUBLIC_PROOF_SCHEMA = "CFB_RECONSTRUCTED_ACQUISITION_READINESS_PUBLIC_V1"


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        out = int(value)
    except (TypeError, ValueError):
        return None
    return out if out >= 0 else None


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_sha(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value.strip().lower()) is not None


def _cache_blockers(cache: object, *, allow_static_seasonless: bool = False) -> list[str]:
    if not isinstance(cache, Sequence) or isinstance(cache, (str, bytes)):
        return ["CACHE_MANIFEST_MISSING_OR_INVALID"]
    blockers: list[str] = []
    seen: set[tuple[str, int | None, int | None, str, str]] = set()
    for index, raw in enumerate(cache):
        if not isinstance(raw, Mapping):
            blockers.append(f"CACHE_ENTRY_INVALID:{index}")
            continue
        endpoint = raw.get("endpoint")
        endpoint_text = str(endpoint or "").strip()
        season_raw = raw.get("season")
        season = None if season_raw is None else _positive_int(season_raw)
        end_week_raw = raw.get("end_week")
        end_week = None if end_week_raw is None else _positive_int(end_week_raw)
        provider = raw.get("provider_contract")
        if not _nonempty(endpoint):
            blockers.append(f"CACHE_ENDPOINT_MISSING:{index}")
        season_optional = allow_static_seasonless and endpoint_text == "/venues"
        if season is None and not season_optional:
            blockers.append(f"CACHE_SEASON_INVALID:{index}")
        if end_week_raw is not None and end_week is None:
            blockers.append(f"CACHE_END_WEEK_INVALID:{index}")
        if not _nonempty(provider):
            blockers.append(f"CACHE_PROVIDER_CONTRACT_MISSING:{index}")
        if not _valid_sha(raw.get("query_sha256")):
            blockers.append(f"CACHE_QUERY_SHA256_INVALID:{index}")
        if not _valid_sha(raw.get("response_sha256")):
            blockers.append(f"CACHE_RESPONSE_SHA256_INVALID:{index}")
        if not _nonempty(raw.get("retrieved_at_utc")):
            blockers.append(f"CACHE_RETRIEVAL_TIMESTAMP_MISSING:{index}")
        if _nonempty(endpoint) and (season is not None or season_optional) and _nonempty(provider):
            ident = (
                endpoint_text,
                season,
                end_week,
                str(provider),
                str(raw.get("query_sha256") or ""),
            )
            if ident in seen:
                blockers.append(f"CACHE_IDENTITY_DUPLICATE:{index}")
            seen.add(ident)
    return blockers


def _legacy_blockers(acquisition: Mapping[str, Any]) -> tuple[list[str], dict[str, Any]]:
    blockers: list[str] = []
    if acquisition.get("status") != "VERIFIED_BEFORE_FIRST_REPLAY_CALL":
        blockers.append("ACCOUNT_QUOTA_STATUS_NOT_VERIFIED")
    if not _nonempty(acquisition.get("active_cfbd_tier")):
        blockers.append("ACTIVE_CFBD_TIER_UNVERIFIED")
    monthly = _positive_int(acquisition.get("monthly_quota"))
    remaining = _positive_int(acquisition.get("remaining_quota"))
    planned = _positive_int(acquisition.get("planned_new_calls"))
    retry = _positive_int(acquisition.get("retry_reserve_calls"))
    if monthly is None or monthly <= 0:
        blockers.append("MONTHLY_QUOTA_UNVERIFIED")
    if remaining is None:
        blockers.append("REMAINING_QUOTA_UNVERIFIED")
    if planned is None:
        blockers.append("PLANNED_CALL_COUNT_INVALID")
    if retry is None:
        blockers.append("RETRY_RESERVE_INVALID")
    if remaining is not None and planned is not None and retry is not None and planned + retry > remaining:
        blockers.append("CALL_PLAN_EXCEEDS_VERIFIED_REMAINING_QUOTA")
    if acquisition.get("verified_cache_reuse") is not True:
        blockers.append("VERIFIED_CACHE_REUSE_NOT_ENABLED")
    if acquisition.get("resume_from_verified_cache") is not True:
        blockers.append("VERIFIED_CACHE_RESUME_NOT_ENABLED")
    if acquisition.get("restart_from_2015") is True:
        blockers.append("FULL_RESTART_FROM_2015_PROHIBITED")
    if acquisition.get("retry_backoff") is not True:
        blockers.append("RETRY_BACKOFF_NOT_ENABLED")
    blockers.extend(_cache_blockers(acquisition.get("cache_manifest")))
    return blockers, {
        "public_proof": False,
        "active_cfbd_tier": acquisition.get("active_cfbd_tier"),
        "monthly_quota": monthly,
        "remaining_quota": remaining,
        "planned_new_calls": planned,
        "retry_reserve_calls": retry,
    }


def _public_blockers(acquisition: Mapping[str, Any]) -> tuple[list[str], dict[str, Any]]:
    blockers: list[str] = []
    if acquisition.get("schema") != PUBLIC_PROOF_SCHEMA:
        blockers.append("PUBLIC_ACQUISITION_PROOF_SCHEMA_INVALID")
    if acquisition.get("status") != "ACQUISITION_COMPLETE_READY_FOR_SELECTION":
        blockers.append("PUBLIC_ACQUISITION_PROOF_STATUS_NOT_READY")
    for key, code in (
        ("account_info_verified", "ACCOUNT_QUOTA_STATUS_NOT_VERIFIED"),
        ("tier_quota_mapping_verified", "TIER_QUOTA_MAPPING_UNVERIFIED"),
        ("call_plan_fits_verified_quota", "CALL_PLAN_QUOTA_FIT_UNVERIFIED"),
        ("verified_cache_reuse", "VERIFIED_CACHE_REUSE_NOT_ENABLED"),
        ("resume_from_verified_cache", "VERIFIED_CACHE_RESUME_NOT_ENABLED"),
        ("retry_backoff", "RETRY_BACKOFF_NOT_ENABLED"),
    ):
        if acquisition.get(key) is not True:
            blockers.append(code)
    if acquisition.get("restart_from_2015") is True:
        blockers.append("FULL_RESTART_FROM_2015_PROHIBITED")
    planned = _positive_int(acquisition.get("planned_new_calls"))
    retry = _positive_int(acquisition.get("retry_reserve_calls"))
    if planned is None:
        blockers.append("PLANNED_CALL_COUNT_INVALID")
    if retry is None:
        blockers.append("RETRY_RESERVE_INVALID")
    if not _valid_sha(acquisition.get("source_manifest_sha256")):
        blockers.append("SOURCE_MANIFEST_SHA256_INVALID")
    if not _valid_sha(acquisition.get("preflight_proof_sha256")):
        blockers.append("PREFLIGHT_PROOF_SHA256_INVALID")
    blockers.extend(_cache_blockers(
        acquisition.get("cache_manifest"),
        allow_static_seasonless=True,
    ))
    authority = acquisition.get("authority")
    if not isinstance(authority, Mapping) or any(value is not False for value in authority.values()):
        blockers.append("PUBLIC_ACQUISITION_AUTHORITY_LEAK")
    return blockers, {
        "public_proof": True,
        "active_cfbd_tier": "VERIFIED_REDACTED",
        "monthly_quota": None,
        "remaining_quota": None,
        "planned_new_calls": planned,
        "retry_reserve_calls": retry,
    }


def audit_cfb_acquisition_readiness(
    policy: Mapping[str, Any],
    acquisition: Mapping[str, Any] | None,
) -> dict[str, Any]:
    blockers: list[str] = []
    if not isinstance(policy.get("acquisition_start_gate"), Mapping):
        blockers.append("FROZEN_ACQUISITION_GATE_MISSING")
    if not isinstance(acquisition, Mapping):
        acquisition = {}
        blockers.append("ACQUISITION_MANIFEST_MISSING")

    if acquisition.get("schema") == PUBLIC_PROOF_SCHEMA:
        lane_blockers, metadata = _public_blockers(acquisition)
    else:
        lane_blockers, metadata = _legacy_blockers(acquisition)
    blockers.extend(lane_blockers)

    ready = not blockers
    cache = acquisition.get("cache_manifest")
    return {
        "schema": CFB_ACQUISITION_READINESS_VERSION,
        "status": "READY_FOR_HISTORICAL_REPLAY" if ready else "BLOCKED_ACQUISITION_NOT_VERIFIED",
        "blockers": list(dict.fromkeys(blockers)),
        "public_proof": metadata["public_proof"],
        "active_cfbd_tier": metadata["active_cfbd_tier"],
        "monthly_quota": metadata["monthly_quota"],
        "remaining_quota": metadata["remaining_quota"],
        "planned_new_calls": metadata["planned_new_calls"],
        "retry_reserve_calls": metadata["retry_reserve_calls"],
        "verified_cache_entries": len(cache) if isinstance(cache, list) else 0,
        "network_call_performed": False,
        "attempt_consumed": False,
        "model_fit_performed": False,
        "model_p_created": False,
        "promotion_authority": False,
        "eligibility_changed": False,
    }


__all__ = [
    "audit_cfb_acquisition_readiness",
    "CFB_ACQUISITION_READINESS_VERSION",
    "PUBLIC_PROOF_SCHEMA",
]
