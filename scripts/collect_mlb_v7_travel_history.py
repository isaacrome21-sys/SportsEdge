#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sportsedge.mlb_v7_travel_history_collect import collect_history_slice


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect a bounded, hash-bound MLB V7 travel-history source slice without granting source-readiness authority.")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    report = collect_history_slice(args.start_date, args.end_date, Path(args.output_dir))
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
