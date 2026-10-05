#!/usr/bin/env python3
"""Warm only the verified CFBD cache portion that safely fits current quota.

This is transport-only acquisition support for the already-frozen reconstructed
selection request plan. It never materializes selection rows, fits/evaluates a
candidate, changes attempt accounting, creates Model_P, or grants promotion,
staking, OFFICIAL, PIT, evidence-clock, or backfill authority.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping

from scripts.acquire_cfb_reconstructed_selection import (
    CONFIG,
    CFBAcquisitionError,
    _fetch_one,
    _load_verified_cache,
    _zero_authority,
    build_request_plan,
)


class CFBPartialCacheWarmError(RuntimeError):
    pass


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_preflight(
    raw: object,
    *,
    total_calls: int,
    actual_cache_hits: int,
) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise CFBPartialCacheWarmError("CFB_CACHE_WARM_PREFLIGHT_MISSING")
    if raw.get("schema_version") != "CFB_CFBD_PROVIDER_PREFLIGHT_V1":
        raise CFBPartialCacheWarmError("CFB_CACHE_WARM_PREFLIGHT_SCHEMA_INVALID")
    if raw.get("status") != "VERIFIED_PARTIAL_CACHE_WARM_ONLY":
        raise CFBPartialCacheWarmError("CFB_CACHE_WARM_PREFLIGHT_STATUS_INVALID")
    if raw.get("historical_replay_calls_performed") != 0:
        raise CFBPartialCacheWarmError("CFB_CACHE_WARM_PREFLIGHT_REPLAY_CALL_LEAK")
    authority = raw.get("authority")
    if not isinstance(authority, Mapping) or any(value is not False for value in authority.values()):
        raise CFBPartialCacheWarmError("CFB_CACHE_WARM_PREFLIGHT_AUTHORITY_LEAK")
    try:
        planned_total = int(raw["planned_total_calls"])
        preflight_hits = int(raw["verified_cache_hits"])
        planned_new = int(raw["planned_new_calls"])
        warm_calls = int(raw["cache_warm_new_calls"])
        reserve = int(raw["retry_reserve_calls"])
        remaining = int(raw["remaining_quota"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CFBPartialCacheWarmError("CFB_CACHE_WARM_PREFLIGHT_QUOTA_INVALID") from exc

    expected_new = total_calls - actual_cache_hits
    if (
        planned_total != total_calls
        or preflight_hits != actual_cache_hits
        or planned_new != expected_new
    ):
        raise CFBPartialCacheWarmError(
            "CFB_CACHE_WARM_PLAN_COUNT_MISMATCH:"
            f"total={planned_total}:{total_calls}:"
            f"cache={preflight_hits}:{actual_cache_hits}:"
            f"new={planned_new}:{expected_new}"
        )
    if warm_calls <= 0 or warm_calls > planned_new:
        raise CFBPartialCacheWarmError("CFB_CACHE_WARM_CALL_CAP_INVALID")
    if remaining < warm_calls + reserve:
        raise CFBPartialCacheWarmError("CFB_CACHE_WARM_RESERVE_VIOLATION")
    return raw


def _count_cache_hits(plan: list[Mapping[str, Any]], cache_root: Path) -> int:
    return sum(
        1
        for item in plan
        if _load_verified_cache(
            cache_root=cache_root,
            query_sha=str(item["query_sha256"]),
        ) is not None
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-preflight", type=Path, required=True)
    parser.add_argument("--private-cache-root", type=Path, required=True)
    parser.add_argument("--public-attestation-out", type=Path, required=True)
    args = parser.parse_args(argv)

    config = _load(CONFIG)
    plan = build_request_plan(config)
    cfbd_cache_root = args.private_cache_root / "cfbd"
    cache_hits_before = _count_cache_hits(plan, cfbd_cache_root)
    network_calls = 0

    try:
        preflight = _validate_preflight(
            _load(args.private_preflight),
            total_calls=len(plan),
            actual_cache_hits=cache_hits_before,
        )
        api_key = str(os.environ.get("CFBD_API_KEY") or "").strip()
        if not api_key:
            raise CFBPartialCacheWarmError("CFBD_API_KEY_MISSING")

        cap = int(preflight["cache_warm_new_calls"])
        for item in plan:
            if network_calls >= cap:
                break
            query_sha = str(item["query_sha256"])
            if _load_verified_cache(cache_root=cfbd_cache_root, query_sha=query_sha) is not None:
                continue
            try:
                _payload, _meta, cached = _fetch_one(
                    item,
                    api_key=api_key,
                    cache_root=cfbd_cache_root,
                    max_attempts=1,
                )
            except CFBAcquisitionError as exc:
                raise CFBPartialCacheWarmError(str(exc)) from exc
            if not cached:
                network_calls += 1

        cache_hits_after = _count_cache_hits(plan, cfbd_cache_root)
        expected_after = cache_hits_before + network_calls
        if cache_hits_after != expected_after:
            raise CFBPartialCacheWarmError(
                f"CFB_CACHE_WARM_POST_COUNT_MISMATCH:{cache_hits_after}:{expected_after}"
            )
        status = (
            "VERIFIED_CACHE_COMPLETE"
            if cache_hits_after == len(plan)
            else "PARTIAL_VERIFIED_CACHE_WARMED"
        )
        report = {
            "schema": "CFB_RECONSTRUCTED_PARTIAL_CACHE_WARM_PUBLIC_V1",
            "status": status,
            "planned_total_request_count": len(plan),
            "verified_cache_entries_before": cache_hits_before,
            "network_calls_performed": network_calls,
            "verified_cache_entries_after": cache_hits_after,
            "remaining_uncached_request_count": len(plan) - cache_hits_after,
            "single_attempt_per_network_request": True,
            "retry_reserve_preserved_by_preflight": True,
            "raw_provider_data_persisted_publicly": False,
            "attempt_consumed": False,
            "evaluation_performed": False,
            "historical_pit_created": False,
            "authority": _zero_authority(),
        }
        rc = 0
    except Exception as exc:
        cache_hits_after = _count_cache_hits(plan, cfbd_cache_root)
        report = {
            "schema": "CFB_RECONSTRUCTED_PARTIAL_CACHE_WARM_PUBLIC_V1",
            "status": "PARTIAL_CACHE_WARM_INTERRUPTED",
            "reason": f"{type(exc).__name__}:{exc}",
            "planned_total_request_count": len(plan),
            "verified_cache_entries_before": cache_hits_before,
            "network_calls_performed": network_calls,
            "verified_cache_entries_after": cache_hits_after,
            "remaining_uncached_request_count": len(plan) - cache_hits_after,
            "single_attempt_per_network_request": True,
            "raw_provider_data_persisted_publicly": False,
            "attempt_consumed": False,
            "evaluation_performed": False,
            "historical_pit_created": False,
            "authority": _zero_authority(),
        }
        rc = 2

    args.public_attestation_out.parent.mkdir(parents=True, exist_ok=True)
    args.public_attestation_out.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, sort_keys=True))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
