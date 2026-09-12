#!/usr/bin/env python3
"""Archive exact The Odds API MLB historical featured-market snapshots.

This collector is evidence-only. It preserves exact provider response bytes and
provider timestamps. It does not interpolate snapshots, build Model_P, change
eligibility, or grant promotion/Truth Gate authority.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = "https://api.the-odds-api.com/v4/historical/sports/baseball_mlb/odds"
SCHEMA = "MLB_THE_ODDS_API_HISTORICAL_ARCHIVE_V1"
DEFAULT_ROOT = Path("artifacts/mlb_v8_replay_sources/THE_ODDS_API_HISTORICAL")
DEFAULT_MARKETS = "h2h,spreads,totals"
DEFAULT_REGIONS = "us"
DEFAULT_ODDS_FORMAT = "american"
KEY_NAMES = (
    "SPORTSEDGE_ODDS_API_KEY",
    "SPORTSEDGE_ODDS_API_KEY_2",
    "SPORTSEDGE_ODDS_API_KEY_3",
    "SPORTSEDGE_ODDS_API_KEY_4",
)


def _parse_utc(value: str) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("MLB_TODDS_REQUEST_TIMESTAMP_TZ_REQUIRED")
    return dt.astimezone(timezone.utc)


def _canonical_request_ts(value: str) -> str:
    return _parse_utc(value).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _provider_error_code(raw: bytes) -> str | None:
    """Extract a non-secret provider error code without retaining response text."""
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    code = payload.get("error_code")
    if code is None:
        return None
    text = str(code).strip()
    return text or None


def _blocked_status(provider_codes: list[str]) -> str:
    """Classify a fully blocked key rotation without weakening evidence rules."""
    if provider_codes == ["OUT_OF_USAGE_CREDITS"]:
        return "BLOCKED_PROVIDER_CREDITS"
    if provider_codes == ["HISTORICAL_UNAVAILABLE_ON_FREE_USAGE_PLAN"]:
        return "BLOCKED_PROVIDER_PLAN"
    return "BLOCKED_PROVIDER_AUTH"


def _atomic(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(raw)
    tmp.replace(path)


def _atomic_json(path: Path, value: Any) -> None:
    _atomic(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def _validate_payload(raw: bytes, requested_at: str) -> dict[str, Any]:
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("MLB_TODDS_RESPONSE_MAPPING_REQUIRED")
    provider_ts = _parse_utc(str(payload.get("timestamp") or ""))
    requested_ts = _parse_utc(requested_at)
    if provider_ts > requested_ts:
        raise ValueError("MLB_TODDS_PROVIDER_TIMESTAMP_AFTER_REQUEST")
    if not isinstance(payload.get("data"), list):
        raise ValueError("MLB_TODDS_RESPONSE_DATA_LIST_REQUIRED")
    return payload


def _secrets() -> list[tuple[int, str]]:
    seen: set[str] = set()
    keys: list[tuple[int, str]] = []
    for slot, name in enumerate(KEY_NAMES, 1):
        value = os.environ.get(name, "").strip()
        if value and value not in seen:
            seen.add(value)
            keys.append((slot, value))
    return keys


def _request(*, key: str, requested_at: str, regions: str, markets: str, odds_format: str) -> tuple[bytes, dict[str, str]]:
    params = {
        "apiKey": key,
        "date": requested_at,
        "regions": regions,
        "markets": markets,
        "oddsFormat": odds_format,
    }
    url = BASE + "?" + urlencode(params)
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "SportsEdge-MLB-Historical/1.1"})
    with urlopen(req, timeout=60) as response:
        return response.read(), {str(k).lower(): str(v) for k, v in response.headers.items()}


def collect_one(*, requested_at: str, root: Path = DEFAULT_ROOT, regions: str = DEFAULT_REGIONS,
                markets: str = DEFAULT_MARKETS, odds_format: str = DEFAULT_ODDS_FORMAT) -> dict[str, Any]:
    requested = _canonical_request_ts(requested_at)
    keys = _secrets()
    if not keys:
        return {"status": "BLOCKED_NO_THE_ODDS_API_KEY", "required_secrets": list(KEY_NAMES)}

    safe = requested.replace(":", "").replace("-", "")
    out_dir = root / safe
    raw_path = out_dir / "snapshot.json"
    meta_path = out_dir / "snapshot.meta.json"
    if raw_path.is_file() and meta_path.is_file():
        raw = raw_path.read_bytes()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("payload_sha256") != _sha(raw):
            raise RuntimeError("MLB_TODDS_EXISTING_RAW_SHA_MISMATCH")
        _validate_payload(raw, requested)
        return {"status": "ALREADY_ARCHIVED", "requested_at": requested, "payload_sha256": _sha(raw), "path": raw_path.as_posix()}

    raw: bytes | None = None
    headers: dict[str, str] = {}
    winning_slot: int | None = None
    attempts: list[dict[str, Any]] = []
    for slot, key in keys:
        try:
            raw, headers = _request(key=key, requested_at=requested, regions=regions, markets=markets, odds_format=odds_format)
            winning_slot = slot
            break
        except HTTPError as exc:
            body = b""
            try:
                body = exc.read()
            except Exception:
                pass
            provider_code = _provider_error_code(body)
            attempt = {
                "key_slot": slot,
                "http_status": int(exc.code),
                "error_body_sha256": _sha(body),
            }
            if provider_code is not None:
                attempt["provider_code"] = provider_code
            attempts.append(attempt)
            if int(exc.code) not in (401, 403):
                return {
                    "status": "BLOCKED_PROVIDER_HTTP",
                    "http_status": int(exc.code),
                    "error_body_sha256": _sha(body),
                    "provider_code": provider_code,
                    "requested_at": requested,
                    "attempted_key_slots": [a["key_slot"] for a in attempts],
                }
        except (URLError, TimeoutError) as exc:
            return {
                "status": "BLOCKED_PROVIDER_NETWORK",
                "reason": type(exc).__name__,
                "requested_at": requested,
                "attempted_key_slots": [a["key_slot"] for a in attempts] + [slot],
            }

    if raw is None or winning_slot is None:
        provider_codes = sorted({str(a["provider_code"]) for a in attempts if a.get("provider_code")})
        return {
            "status": _blocked_status(provider_codes),
            "requested_at": requested,
            "attempts": attempts,
            "provider_codes": provider_codes,
            "configured_unique_key_slots": len(keys),
        }

    payload = _validate_payload(raw, requested)
    digest = _sha(raw)
    meta = {
        "schema": SCHEMA,
        "provider": "The Odds API",
        "source": "THE_ODDS_API_HISTORICAL",
        "endpoint": "/v4/historical/sports/baseball_mlb/odds",
        "requested_at": requested,
        "provider_timestamp": payload["timestamp"],
        "previous_timestamp": payload.get("previous_timestamp"),
        "next_timestamp": payload.get("next_timestamp"),
        "regions": regions,
        "markets": markets,
        "odds_format": odds_format,
        "payload_sha256": digest,
        "bytes": len(raw),
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "quota_remaining": headers.get("x-requests-remaining"),
        "quota_used": headers.get("x-requests-used"),
        "credential_slot": winning_slot,
        "interpolated": False,
        "reconstructed": False,
        "promotion_authority": False,
        "may_change_market_eligibility": False,
    }
    _atomic(raw_path, raw)
    _atomic_json(meta_path, meta)
    return {
        "status": "ARCHIVED_EXACT_PROVIDER_SNAPSHOT",
        "requested_at": requested,
        "provider_timestamp": payload["timestamp"],
        "event_count": len(payload["data"]),
        "payload_sha256": digest,
        "path": raw_path.as_posix(),
        "credential_slot": winning_slot,
        "promotion_authority": False,
    }


def self_test() -> int:
    assert _canonical_request_ts("2026-06-05T22:35:00Z") == "2026-06-05T22:35:00Z"
    assert _provider_error_code(b'{"error_code":"OUT_OF_USAGE_CREDITS"}') == "OUT_OF_USAGE_CREDITS"
    assert _provider_error_code(b"not-json") is None
    assert _blocked_status(["OUT_OF_USAGE_CREDITS"]) == "BLOCKED_PROVIDER_CREDITS"
    assert _blocked_status(["HISTORICAL_UNAVAILABLE_ON_FREE_USAGE_PLAN"]) == "BLOCKED_PROVIDER_PLAN"
    assert _blocked_status(["INVALID_KEY"]) == "BLOCKED_PROVIDER_AUTH"
    raw = json.dumps({
        "timestamp": "2026-06-05T22:30:00Z",
        "previous_timestamp": "2026-06-05T22:25:00Z",
        "next_timestamp": "2026-06-05T22:35:00Z",
        "data": [],
    }).encode()
    payload = _validate_payload(raw, "2026-06-05T22:35:00Z")
    assert payload["timestamp"] == "2026-06-05T22:30:00Z"
    try:
        _validate_payload(json.dumps({"timestamp": "2026-06-05T22:40:00Z", "data": []}).encode(), "2026-06-05T22:35:00Z")
    except ValueError as exc:
        assert str(exc) == "MLB_TODDS_PROVIDER_TIMESTAMP_AFTER_REQUEST"
    else:
        raise AssertionError("future provider timestamp accepted")
    print(json.dumps({"status": "SELF_TEST_OK", "secret_written": False, "promotion_authority": False}))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    ap.add_argument("--regions", default=DEFAULT_REGIONS)
    ap.add_argument("--markets", default=DEFAULT_MARKETS)
    ap.add_argument("--odds-format", default=DEFAULT_ODDS_FORMAT)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not args.date:
        ap.error("--date is required unless --self-test is used")
    out = collect_one(requested_at=args.date, root=args.root, regions=args.regions, markets=args.markets, odds_format=args.odds_format)
    print(json.dumps(out, sort_keys=True))
    return 0 if out["status"] in {"ARCHIVED_EXACT_PROVIDER_SNAPSHOT", "ALREADY_ARCHIVED"} else 78


if __name__ == "__main__":
    raise SystemExit(main())
