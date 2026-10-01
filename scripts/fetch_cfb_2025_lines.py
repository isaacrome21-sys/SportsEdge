#!/usr/bin/env python3
"""Fetch 2025 CFBD last-stored regular-season lines into runner-private JSON."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

CFBD_BASE = "https://api.collegefootballdata.com"


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_lines(*, api_key: str, opener=urlopen) -> dict:
    key = str(api_key or "").strip()
    if not key:
        raise RuntimeError("CFBD_API_KEY_MISSING")
    params = urlencode({"year": 2025, "seasonType": "regular"})
    request = Request(
        f"{CFBD_BASE}/lines?{params}",
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
    )
    with opener(request, timeout=45) as response:
        raw = json.loads(response.read().decode("utf-8"))
    if not isinstance(raw, list):
        raise RuntimeError("CFB_2025_LINES_RESPONSE_NOT_LIST")

    rows = []
    for game in raw:
        if not isinstance(game, dict):
            continue
        game_id = str(game.get("id") or game.get("gameId") or "").strip()
        if not game_id:
            continue
        offers = game.get("lines")
        if not isinstance(offers, list):
            continue
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            provider = str(offer.get("provider") or "").strip()
            spread = _number(offer.get("spread"))
            total = _number(offer.get("overUnder"))
            if not provider or spread is None or total is None:
                continue
            rows.append(
                {
                    "game_id": game_id,
                    "provider": provider,
                    "home_spread": spread,
                    "total": total,
                }
            )
    if not rows:
        raise RuntimeError("CFB_2025_LINES_EMPTY")
    return {
        "schema": "CFB_2025_CFBD_LAST_STORED_LINES_V1",
        "season": 2025,
        "season_type": "regular",
        "close_time_certified": False,
        "rows": rows,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    payload = fetch_lines(api_key=os.environ.get("CFBD_API_KEY", ""))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "CFB_2025_LINES_FETCHED_PRIVATELY", "rows": len(payload["rows"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
