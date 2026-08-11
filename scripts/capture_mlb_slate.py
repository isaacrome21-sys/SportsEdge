#!/usr/bin/env python3
import argparse
import json
from datetime import date

from sportsedge.mlb_source import fetch_schedule, snapshot_to_dict


def main() -> int:
    p = argparse.ArgumentParser(description="Capture MLB schedule/probable-pitcher snapshot")
    p.add_argument("--date", default=date.today().isoformat(), help="YYYY-MM-DD")
    args = p.parse_args()
    snapshots = fetch_schedule(args.date)
    print(json.dumps({"date": args.date, "games": [snapshot_to_dict(x) for x in snapshots]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
