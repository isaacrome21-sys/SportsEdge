"""Fail-closed readiness gate for reconstructed CFB historical acquisition."""
# Provider-preflight readiness is non-authoritative and must not consume an evaluation attempt.
# Public-splits PYTHONPATH fix retrigger for required CFB readiness check.
# Public-splits decoder fix retrigger for required CFB readiness check.
# DK prop clock retrigger for required CFB readiness check.
# Blueprint ops park retrigger for required CFB readiness check.
# DK-only board snapshot retrigger for required CFB readiness check.
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
CFB_ACQUISITION_READINESS_VERSION = "CFB_ACQUISITION_READINESS_V1"


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


def _cache_blockers(cache: object) -> list[str]:
    if not isinstance(cache, Sequence) or isinstance(cache, (str, bytes)):
        return ["CACHE_MANIFEST_MISSING_OR_INVALID"]
    blockers: list[str] = []
    seen: set[tuple[str, int, int | None, str]] = set()
    for index, raw in enumerate(cache):
        if not isinstance(raw, Mapping):
            blockers.append(f"CACHE_ENTRY_INVALID:{index}")
            continue
        endpoint = raw.get("endpoint")
        season = _positive_int(raw.get("season"))
        end_week_raw = raw.get("end_week")
        end_week = None if end_week_raw is None else _positive_int(end_week_raw)
        provider = raw.get("provider_contract")
        if not _nonempty(endpoint): blockers.append(f"CACHE_ENDPOINT_MISSING:{index}")
        if season is None: blockers.append(f"CACHE_SEASON_INVALID:{index}")
        if end_week_raw is not None and end_week is None: blockers.append(f"CACHE_END_WEEK_INVALID:{index}")
        if not _nonempty(provider): blockers.append(f"CACHE_PROVIDER_CONTRACT_MISSING:{index}")
        if not _valid_sha(raw.get("query_sha256")): blockers.append(f"CACHE_QUERY_SHA256_INVALID:{index}")
        if not _valid_sha(raw.get("response_sha256")): blockers.append(f"CACHE_RESPONSE_SHA256_INVALID:{index}")
        if not _nonempty(raw.get("retrieved_at_utc")): blockers.append(f"CACHE_RETRIEVAL_TIMESTAMP_MISSING:{index}")
        if _nonempty(endpoint) and season is not None and _nonempty(provider):
            ident = (str(endpoint), season, end_week, str(provider))
            if ident in seen: blockers.append(f"CACHE_IDENTITY_DUPLICATE:{index}")
            seen.add(ident)
    return blockers


def audit_cfb_acquisition_readiness(policy: Mapping[str, Any], acquisition: Mapping[str, Any] | None) -> dict[str, Any]:
    blockers: list[str] = []
    if not isinstance(policy.get("acquisition_start_gate"), Mapping):
        blockers.append("FROZEN_ACQUISITION_GATE_MISSING")
    if not isinstance(acquisition, Mapping):
        acquisition = {}
        blockers.append("ACQUISITION_MANIFEST_MISSING")
    if acquisition.get("status") != "VERIFIED_BEFORE_FIRST_REPLAY_CALL": blockers.append("ACCOUNT_QUOTA_STATUS_NOT_VERIFIED")
    if not _nonempty(acquisition.get("active_cfbd_tier")): blockers.append("ACTIVE_CFBD_TIER_UNVERIFIED")
    monthly = _positive_int(acquisition.get("monthly_quota"))
    remaining = _positive_int(acquisition.get("remaining_quota"))
    planned = _positive_int(acquisition.get("planned_new_calls"))
    retry = _positive_int(acquisition.get("retry_reserve_calls"))
    if monthly is None or monthly <= 0: blockers.append("MONTHLY_QUOTA_UNVERIFIED")
    if remaining is None: blockers.append("REMAINING_QUOTA_UNVERIFIED")
    if planned is None: blockers.append("PLANNED_CALL_COUNT_INVALID")
    if retry is None: blockers.append("RETRY_RESERVE_INVALID")
    if remaining is not None and planned is not None and retry is not None and planned + retry > remaining:
        blockers.append("CALL_PLAN_EXCEEDS_VERIFIED_REMAINING_QUOTA")
    if acquisition.get("verified_cache_reuse") is not True: blockers.append("VERIFIED_CACHE_REUSE_NOT_ENABLED")
    if acquisition.get("resume_from_verified_cache") is not True: blockers.append("VERIFIED_CACHE_RESUME_NOT_ENABLED")
    if acquisition.get("restart_from_2015") is True: blockers.append("FULL_RESTART_FROM_2015_PROHIBITED")
    if acquisition.get("retry_backoff") is not True: blockers.append("RETRY_BACKOFF_NOT_ENABLED")
    blockers.extend(_cache_blockers(acquisition.get("cache_manifest")))
    ready = not blockers
    return {
        "schema": CFB_ACQUISITION_READINESS_VERSION,
        "status": "READY_FOR_HISTORICAL_REPLAY" if ready else "BLOCKED_ACQUISITION_NOT_VERIFIED",
        "blockers": blockers,
        "active_cfbd_tier": acquisition.get("active_cfbd_tier"),
        "monthly_quota": monthly,
        "remaining_quota": remaining,
        "planned_new_calls": planned,
        "retry_reserve_calls": retry,
        "verified_cache_entries": len(acquisition.get("cache_manifest") or []) if isinstance(acquisition.get("cache_manifest"), list) else 0,
        "network_call_performed": False,
        "attempt_consumed": False,
        "model_fit_performed": False,
        "model_p_created": False,
        "promotion_authority": False,
        "eligibility_changed": False,
    }

__all__ = ["audit_cfb_acquisition_readiness"]
