#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sportsedge.mlb_v7_travel_history import probe_one_final_game


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe official MLB historical endpoints for V7 travel-source recovery without granting model authority.")
    parser.add_argument("--date", default="2025-04-01")
    parser.add_argument("--output", default="artifacts/mlb-v7-travel-history/probe.json")
    args = parser.parse_args()

    report = probe_one_final_game(args.date)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
