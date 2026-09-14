#!/usr/bin/env python3
"""One-shot, zero-authority Odds API authentication diagnostic.

This script exists only to classify paid-endpoint authentication failures that
would otherwise be collapsed into a generic HTTP 401 by the closing-line
archive. It never prints API-key values or request URLs and only persists an
allow-listed provider error code plus quota headers.

No Model_P, promotion, Truth Gate, staking, OFFICIAL, production-registry, or
evidence-clock authority is granted by this diagnostic.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

API_ROOT = "https://api.the-odds-api.com/v4"
SPORT_KEY = "americanfootball_nfl"
KEY_ENV_VARS = (
    "SPORTSEDGE_ODDS_API_KEY",
    "SPORTSEDGE_ODDS_API_KEY_2",
    "SPORTSEDGE_ODDS_API_KEY_3",
    "SPORTSEDGE_ODDS_API_KEY_4",
)
ALLOWED_PROVIDER_ERROR_CODES = {
    "MISSING_KEY",
    "INVALID_KEY",
    "DEACTIVATED_KEY",
    "EXCEEDED_FREQ_LIMIT",
    "OUT_OF_USAGE_CREDITS",
    "MISSING_REGION",
    "INVALID_REGION",
    "INVALID_BOOKMAKERS",
}
QUOTA_HEADERS = (
    "x-requests-remaining",
    "x-requests-used",
    "x-requests-last",
)


def configured_keys(environ: Mapping[str, str] | None = None) -> list[tuple[str, str]]:
    env = environ if environ is not None else os.environ
    return [(name, str(env.get(name, "")).strip()) for name in KEY_ENV_VARS if str(env.get(name, "")).strip()]


def _provider_error_code(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read(16384)
        payload = json.loads(raw.decode("utf-8")) if raw else {}
    except Exception:
        payload = {}
    code = str(payload.get("error_code") or "").strip().upper()
    if code in ALLOWED_PROVIDER_ERROR_CODES:
        return code
    return f"HTTP_{int(exc.code)}_UNCLASSIFIED"


def _quota_headers(headers: Any) -> dict[str, str]:
    if headers is None:
        return {}
    out: dict[str, str] = {}
    for name in QUOTA_HEADERS:
        value = headers.get(name)
        if value is not None:
            out[name] = str(value)
    return out


def _build_url(key: str) -> str:
    query = urllib.parse.urlencode(
        {
            "apiKey": key,
            "markets": "h2h",
            "bookmakers": "draftkings",
            "oddsFormat": "american",
        }
    )
    return f"{API_ROOT}/sports/{SPORT_KEY}/odds?{query}"


def diagnose(
    key_slots: Iterable[tuple[str, str]],
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    slots = list(key_slots)
    if not slots:
        return {
            "schema_version": "ODDS_API_AUTH_DIAGNOSTIC_V1",
            "state": "BLOCKED",
            "reason": "NO_CONFIGURED_KEY",
            "tested_key_slots": [],
            "attempts": [],
            "authority": _zero_authority(),
        }

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
                attempt.update(
                    {
                        "state": "AUTHENTICATED",
                        "http_status": int(getattr(response, "status", 200) or 200),
                        "events_returned": len(payload),
                        "quota_headers": _quota_headers(getattr(response, "headers", None)),
                    }
                )
                attempts.append(attempt)
                return {
                    "schema_version": "ODDS_API_AUTH_DIAGNOSTIC_V1",
                    "state": "AUTHENTICATED",
                    "authenticated_key_slot": slot_name,
                    "tested_key_slots": [x["key_slot"] for x in attempts],
                    "attempts": attempts,
                    "authority": _zero_authority(),
                }
        except urllib.error.HTTPError as exc:
            attempt.update(
                {
                    "state": "BLOCKED",
                    "http_status": int(exc.code),
                    "provider_error_code": _provider_error_code(exc),
                    "quota_headers": _quota_headers(getattr(exc, "headers", None)),
                }
            )
            attempts.append(attempt)
        except Exception:
            attempt.update({"state": "BLOCKED", "reason": "TRANSPORT_FAILURE_REDACTED"})
            attempts.append(attempt)

    return {
        "schema_version": "ODDS_API_AUTH_DIAGNOSTIC_V1",
        "state": "BLOCKED",
        "reason": "NO_AUTHENTICATED_KEY_SLOT",
        "tested_key_slots": [x["key_slot"] for x in attempts],
        "attempts": attempts,
        "authority": _zero_authority(),
    }


def _zero_authority() -> dict[str, bool]:
    return {
        "model_p_input": False,
        "promotion_authority": False,
        "truth_gate_input": False,
        "staking_authority": False,
        "official_authority": False,
        "production_registry_authority": False,
        "evidence_clock_authority": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    report = diagnose(configured_keys())
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["state"] == "AUTHENTICATED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
