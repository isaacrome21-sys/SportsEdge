#!/usr/bin/env python3
import argparse
import json
from datetime import date

from sportsedge.live_capture import capture_slate, capture_result_to_dict


def main() -> int:
    p = argparse.ArgumentParser(description="Capture MLB schedule plus current lineup state")
    p.add_argument("--date", default=date.today().isoformat(), help="YYYY-MM-DD")
    args = p.parse_args()
    results = capture_slate(args.date)
    payload = {
        "date": args.date,
        "games": [capture_result_to_dict(x) for x in results],
        "blocked_games": sum(x.status == "CAPTURE_BLOCKED" for x in results),
        "confirmed_games": sum(x.status == "LINEUPS_CONFIRMED" for x in results),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 1 if results and all(x.status == "CAPTURE_BLOCKED" for x in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
