#!/usr/bin/env python3
"""Fetch one lead-time-labelled past forecast hour from Open-Meteo (research only).

  python3 scripts/capture_open_meteo_previous_runs.py --lat 30.285 --lon -97.732 \
      --valid 2026-10-25T00:00:00Z --lead-days 1 --decision 2026-10-24T22:00:00Z

Exit 0 with a JSON record; exit 2 on refusal (missing hour, lead too short, bad data).
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sportsedge.open_meteo_previous_runs import (  # noqa: E402
    PreviousRunsError, hour_record, previous_runs_url,
)


def _instant(text: str) -> datetime:
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise argparse.ArgumentTypeError(f"datetime needs an offset: {text}")
    return value


def main(argv: list[str] | None = None, fetch=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--valid", type=_instant, required=True)
    p.add_argument("--lead-days", type=int, default=1)
    p.add_argument("--decision", type=_instant, default=None)
    a = p.parse_args(argv)
    try:
        url = previous_runs_url(a.lat, a.lon, a.valid, a.lead_days)
        if fetch is None:
            with urllib.request.urlopen(url, timeout=20) as resp:
                payload = json.loads(resp.read())
        else:
            payload = fetch(url)
        record = hour_record(payload, a.valid, a.lead_days, decision_time=a.decision)
    except (PreviousRunsError, ValueError, OSError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    record["source_url"] = url
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
