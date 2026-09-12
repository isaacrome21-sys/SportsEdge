#!/usr/bin/env python3
"""Archive the OddsPapi market catalogue used to interpret immutable histories."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = "https://api.oddspapi.io/v4"
OUT = Path("artifacts/mlb_v8_replay_sources/ODDSPAPI_HISTORICAL/catalog/markets.json")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def atomic(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(raw)
    tmp.replace(path)


def main() -> int:
    key = os.environ.get("SPORTSEDGE_ODDSPAPI_KEY", "").strip()
    if not key:
        print(json.dumps({"status": "BLOCKED_NO_ODDSPAPI_KEY", "required_secret": "SPORTSEDGE_ODDSPAPI_KEY"}))
        return 78
    url = f"{BASE}/markets?" + urlencode({"apiKey": key, "language": "en"})
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "SportsEdge-V8-OddsPapi-Catalog/1.0"})
    try:
        with urlopen(req, timeout=60) as response:
            raw = response.read()
            headers = {str(k).lower(): str(v) for k, v in response.headers.items()}
    except HTTPError as exc:
        if exc.code in (401, 403):
            print(json.dumps({
                "status": "BLOCKED_ODDSPAPI_CREDENTIAL_UNAUTHORIZED",
                "http_status": exc.code,
                "required_secret": "SPORTSEDGE_ODDSPAPI_KEY",
                "provider": "ODDSPAPI_HISTORICAL",
            }, sort_keys=True))
            return 79
        print(json.dumps({
            "status": "PROVIDER_HTTP_BLOCKED",
            "http_status": exc.code,
            "provider": "ODDSPAPI_HISTORICAL",
        }, sort_keys=True))
        return 80
    except (URLError, TimeoutError) as exc:
        print(json.dumps({
            "status": "PROVIDER_NETWORK_BLOCKED",
            "reason": type(exc).__name__,
            "provider": "ODDSPAPI_HISTORICAL",
        }, sort_keys=True))
        return 81
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, list) or not payload:
        print(json.dumps({"status": "ODDSPAPI_MARKET_CATALOG_INVALID"}, sort_keys=True))
        return 82
    atomic(OUT, raw)
    meta = {
        "source": "ODDSPAPI_MARKET_CATALOG",
        "endpoint": "/v4/markets",
        "request_params_secret_free": {"language": "en"},
        "payload_sha256": sha(raw),
        "bytes": len(raw),
        "etag": headers.get("etag"),
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    atomic(OUT.with_name("markets.meta.json"), (json.dumps(meta, indent=2, sort_keys=True) + "\n").encode())
    print(json.dumps({"status": "CATALOG_ARCHIVED", "markets": len(payload), "sha256": sha(raw)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
