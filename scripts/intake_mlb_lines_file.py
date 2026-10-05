#!/usr/bin/env python3
"""Plain-text MLB lines -> canonical manual input for the fast runtime.

Transcription/transport only. Uses the existing phone-line parser and schedule
resolver; it does not create probabilities or alter model inputs beyond binding
human-readable teams/subjects to the canonical manual quote contract.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from sportsedge.mlb_resolve import build_bound_input
from sportsedge.mlb_source import fetch_schedule

CHICAGO = ZoneInfo("America/Chicago")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--observed-at", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--book", default="draftkings")
    args = ap.parse_args()

    observed = datetime.fromisoformat(args.observed_at.replace("Z", "+00:00"))
    if observed.tzinfo is None:
        raise SystemExit("MLB_FAST_TEXT_OBSERVED_AT_TZ_REQUIRED")
    local = observed.astimezone(CHICAGO)
    slate = local.date().isoformat()
    nxt = (local.date() + timedelta(days=1)).isoformat()

    text = Path(args.input).read_text(encoding="utf-8")
    schedule = list(fetch_schedule(slate)) + list(fetch_schedule(nxt))
    payload = build_bound_input(
        text,
        observed_at=local.isoformat(),
        schedule=schedule,
        book=args.book,
    )
    payload["schedule_snapshot"] = [asdict(game) for game in schedule]
    payload["intake"] = {
        "mode": "FAST_TEXT_INTAKE",
        "timestamp_source": "INTAKE_STAMPED",
        "observed_at": local.isoformat(),
        "book": args.book,
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "OK",
        "rows": len(payload.get("rows") or []),
        "slate": slate,
        "output": str(out),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
