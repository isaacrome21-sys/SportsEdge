#!/usr/bin/env python3
"""Collect one normalized NWS game-window weather record (research only).

Free public API (api.weather.gov) -- no key, no account. The record is a
provenance-carrying snapshot of the observation/forecast feed behind the
declared (PENDING_VALIDATION) weather thresholds. It is never a pricing
input: see sportsedge/nws_weather_source.py.

Example (Texas vs Ole Miss kickoff window, Darrell K Royal Stadium):
  python3 scripts/collect_nws_weather.py \
    --lat 30.285 --lon -97.732 \
    --start 2026-10-24T23:30:00Z --end 2026-10-25T02:30:00Z \
    --out artifacts/nws_weather/texas_olemiss_20261024.json

Exit 0 with a record whose status is VERIFIED_OBSERVATION or UNVERIFIED
(a data verdict, not a failure); exit 2 on transport/contract failure.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sportsedge.nws_weather_source import (  # noqa: E402
    NWSWeatherSourceError, game_window_weather,
)


def _instant(text: str) -> datetime:
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError(f"datetime needs an offset: {text}")
    return parsed.astimezone(timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--start", type=_instant, required=True,
                        help="game window start (ISO 8601, e.g. kickoff UTC)")
    parser.add_argument("--end", type=_instant, required=True,
                        help="game window end (ISO 8601)")
    parser.add_argument("--out", type=Path, default=None,
                        help="optional path to also write the JSON record")
    args = parser.parse_args()

    try:
        record = game_window_weather(
            args.lat, args.lon, window_start=args.start, window_end=args.end)
    except NWSWeatherSourceError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    text = json.dumps(record, indent=2, sort_keys=True)
    print(text)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
