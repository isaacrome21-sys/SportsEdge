#!/usr/bin/env python3
"""Append a secret-free metered-provider usage attribution row.

This records observed provider accounting; it does not infer cost when quota
headers are unavailable.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--lane", required=True)
    p.add_argument("--provider", required=True)
    p.add_argument("--endpoint", required=True)
    p.add_argument("--markets", default="")
    p.add_argument("--run-id", default="")
    p.add_argument("--quota-before", type=int)
    p.add_argument("--quota-after", type=int)
    args = p.parse_args()
    delta = None
    if args.quota_before is not None and args.quota_after is not None:
        delta = args.quota_before - args.quota_after
        if delta < 0:
            raise SystemExit("QUOTA_DELTA_INVALID")
    row = {
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "lane": args.lane,
        "provider": args.provider,
        "endpoint": args.endpoint,
        "markets": sorted({x.strip() for x in args.markets.split(",") if x.strip()}),
        "run_id": args.run_id or None,
        "quota_before": args.quota_before,
        "quota_after": args.quota_after,
        "observed_quota_delta": delta,
        "cost_inference": "OBSERVED_DELTA" if delta is not None else "UNKNOWN",
        "contains_credentials": False,
    }
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")
    print(json.dumps(row, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
