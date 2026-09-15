#!/usr/bin/env python3
"""Zero-credit, secret-safe quota readiness probe for The Odds API.

The provider's /v4/sports endpoint is documented as zero usage cost while still
returning x-requests-remaining/used/last.  This module treats those headers as
control-plane state: missing or malformed quota telemetry fails closed.

The implementation is SportsEdge-owned.  Public repositories informed the
architecture (quota telemetry, reserved budget, fail-closed unknown state), but
no third-party source code is copied here.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

API_URL = "https://api.the-odds-api.com/v4/sports/"
KEY_ENV_VARS = (
    "SPORTSEDGE_ODDS_API_KEY",
    "SPORTSEDGE_ODDS_API_KEY_2",
    "SPORTSEDGE_ODDS_API_KEY_3",
    "SPORTSEDGE_ODDS_API_KEY_4",
)
QUOTA_HEADERS = (
    "x-requests-remaining",
    "x-requests-used",
    "x-requests-last",
)
ALLOWED_PROVIDER_ERROR_CODES = {
    "MISSING_KEY",
    "INVALID_KEY",
    "DEACTIVATED_KEY",
    "EXCEEDED_FREQ_LIMIT",
    "OUT_OF_USAGE_CREDITS",
}


def configured_keys(environ: Mapping[str, str] | None = None) -> list[tuple[str, str]]:
    env = environ if environ is not None else os.environ
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name in KEY_ENV_VARS:
        key = str(env.get(name, "")).strip()
        if key and key not in seen:
            seen.add(key)
            out.append((name, key))
    return out


def _provider_error_code(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read(16384)
        payload = json.loads(raw.decode("utf-8")) if raw else {}
    except Exception:
        payload = {}
    code = str(payload.get("error_code") or payload.get("code") or "").strip().upper()
    return code if code in ALLOWED_PROVIDER_ERROR_CODES else f"HTTP_{int(exc.code)}_UNCLASSIFIED"


def _quota_headers(headers: Any) -> tuple[dict[str, int], str | None]:
    if headers is None:
        return {}, "MISSING_QUOTA_HEADERS"
    out: dict[str, int] = {}
    for name in QUOTA_HEADERS:
        raw = headers.get(name)
        if raw is None:
            return {}, f"MISSING_{name.upper().replace('-', '_')}"
        text = str(raw).strip()
        if not text.isdigit():
            return {}, f"INVALID_{name.upper().replace('-', '_')}"
        out[name] = int(text)
    return out, None


def _build_url(key: str) -> str:
    return API_URL + "?" + urllib.parse.urlencode({"apiKey": key})


def zero_authority() -> dict[str, bool]:
    return {
        "model_p_input": False,
        "promotion_authority": False,
        "truth_gate_input": False,
        "staking_authority": False,
        "official_authority": False,
        "production_registry_authority": False,
        "evidence_clock_authority": False,
        "backfill_authority": False,
    }


def probe_quota(
    key_slots: Iterable[tuple[str, str]],
    *,
    minimum_remaining: int,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    if not isinstance(minimum_remaining, int) or minimum_remaining < 0:
        raise ValueError("minimum_remaining must be a non-negative integer")

    attempts: list[dict[str, Any]] = []
    slots = list(key_slots)
    if not slots:
        return {
            "schema_version": "SPORTSEDGE_ODDS_API_QUOTA_PREFLIGHT_V1",
            "state": "BLOCKED",
            "reason": "NO_CONFIGURED_KEY",
            "minimum_remaining": minimum_remaining,
            "max_remaining": None,
            "ready_key_slots": [],
            "tested_key_slots": [],
            "attempts": [],
            "authority": zero_authority(),
        }

    ready: list[str] = []
    observed_remaining: list[int] = []
    for slot_name, key in slots:
        attempt: dict[str, Any] = {"key_slot": slot_name}
        try:
            with opener(_build_url(key), timeout=30) as response:
                body = response.read()
                payload = json.loads(body.decode("utf-8")) if body else []
                if not isinstance(payload, list):
                    attempt.update({"state": "BLOCKED", "reason": "MALFORMED_SUCCESS_PAYLOAD"})
                    attempts.append(attempt)
                    continue
                quota, quota_error = _quota_headers(getattr(response, "headers", None))
                if quota_error:
                    attempt.update({
                        "state": "BLOCKED",
                        "http_status": int(getattr(response, "status", 200) or 200),
                        "reason": quota_error,
                    })
                    attempts.append(attempt)
                    continue
                remaining = quota["x-requests-remaining"]
                observed_remaining.append(remaining)
                state = "READY" if remaining >= minimum_remaining else "BELOW_RESERVE"
                attempt.update({
                    "state": state,
                    "http_status": int(getattr(response, "status", 200) or 200),
                    "quota_headers": quota,
                })
                attempts.append(attempt)
                if state == "READY":
                    ready.append(slot_name)
        except urllib.error.HTTPError as exc:
            quota, _ = _quota_headers(getattr(exc, "headers", None))
            if quota:
                observed_remaining.append(quota["x-requests-remaining"])
            attempt.update({
                "state": "BLOCKED",
                "http_status": int(exc.code),
                "provider_error_code": _provider_error_code(exc),
                "quota_headers": quota,
            })
            attempts.append(attempt)
        except Exception:
            attempt.update({"state": "BLOCKED", "reason": "TRANSPORT_FAILURE_REDACTED"})
            attempts.append(attempt)

    max_remaining = max(observed_remaining) if observed_remaining else None
    if ready:
        state, reason = "READY", "RESERVE_SATISFIED"
    elif max_remaining is not None:
        state, reason = "BLOCKED", "INSUFFICIENT_REMAINING_CREDITS"
    else:
        state, reason = "BLOCKED", "QUOTA_STATE_UNKNOWN"
    return {
        "schema_version": "SPORTSEDGE_ODDS_API_QUOTA_PREFLIGHT_V1",
        "state": state,
        "reason": reason,
        "minimum_remaining": minimum_remaining,
        "max_remaining": max_remaining,
        "ready_key_slots": ready,
        "tested_key_slots": [x["key_slot"] for x in attempts],
        "attempts": attempts,
        "authority": zero_authority(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minimum-remaining", type=int, required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    report = probe_quota(configured_keys(), minimum_remaining=args.minimum_remaining)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["state"] == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
