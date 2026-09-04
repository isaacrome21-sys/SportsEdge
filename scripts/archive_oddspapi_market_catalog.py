#!/usr/bin/env python3
"""Archive the OddsPapi market catalogue used to interpret immutable histories."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
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
        return 2
    url = f"{BASE}/markets?" + urlencode({"apiKey": key, "language": "en"})
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "SportsEdge-V8-OddsPapi-Catalog/1.0"})
    with urlopen(req, timeout=60) as response:
        raw = response.read()
        headers = {str(k).lower(): str(v) for k, v in response.headers.items()}
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, list) or not payload:
        raise SystemExit("ODDSPAPI_MARKET_CATALOG_INVALID")
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
