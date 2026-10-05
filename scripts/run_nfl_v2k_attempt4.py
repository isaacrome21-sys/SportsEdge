#!/usr/bin/env python3
"""Run NFL V2K Attempt-4 market-anchored residual validation."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sportsedge.sports.nfl import v2k_attempt1_validation as a1
from sportsedge.sports.nfl import v2k_attempt4_validation as v4


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--schedule", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    contract = v4.preflight()
    schedule = a1.load_schedule(args.schedule)
    result = v4.evaluate(schedule, contract)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
