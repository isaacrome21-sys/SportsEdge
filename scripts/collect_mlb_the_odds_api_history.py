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


def _secret() -> str:
    return os.environ.get("SPORTSEDGE_ODDS_API_KEY", "").strip()


def _request(*, key: str, requested_at: str, regions: str, markets: str, odds_format: str) -> tuple[bytes, dict[str, str]]:
    params = {
        "apiKey": key,
        "date": requested_at,
        "regions": regions,
        "markets": markets,
        "oddsFormat": odds_format,
    }
    url = BASE + "?" + urlencode(params)
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "SportsEdge-MLB-Historical/1.0"})
    with urlopen(req, timeout=60) as response:
        return response.read(), {str(k).lower(): str(v) for k, v in response.headers.items()}


def collect_one(*, requested_at: str, root: Path = DEFAULT_ROOT, regions: str = DEFAULT_REGIONS,
                markets: str = DEFAULT_MARKETS, odds_format: str = DEFAULT_ODDS_FORMAT) -> dict[str, Any]:
    requested = _canonical_request_ts(requested_at)
    key = _secret()
    if not key:
        return {"status": "BLOCKED_NO_THE_ODDS_API_KEY", "required_secret": "SPORTSEDGE_ODDS_API_KEY"}

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

    try:
        raw, headers = _request(key=key, requested_at=requested, regions=regions, markets=markets, odds_format=odds_format)
    except HTTPError as exc:
        body = b""
        try:
            body = exc.read()
        except Exception:
            pass
        code = int(exc.code)
        status = "BLOCKED_PROVIDER_AUTH" if code in (401, 403) else "BLOCKED_PROVIDER_HTTP"
        return {"status": status, "http_status": code, "error_body_sha256": _sha(body), "requested_at": requested}
    except (URLError, TimeoutError) as exc:
        return {"status": "BLOCKED_PROVIDER_NETWORK", "reason": type(exc).__name__, "requested_at": requested}

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
        "promotion_authority": False,
    }


def self_test() -> int:
    assert _canonical_request_ts("2026-06-05T22:35:00Z") == "2026-06-05T22:35:00Z"
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
