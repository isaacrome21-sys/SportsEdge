#!/usr/bin/env python3
"""Inspect an existing NBA V2 chronological screen; never capture/reprice games.

Example: python scripts/audit_nba_total_directions.py --screen screen.json
The output is a research diagnostic, never a forward-test entry or PLAY.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sportsedge.research.nba_total_direction_audit_v1 import audit_total_directions


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--screen", type=Path, required=True,
                    help="Existing read-only chronological_total_screen JSON")
    ap.add_argument("--output", type=Path,
                    help="Optional research diagnostic JSON; stdout by default")
    args = ap.parse_args(argv)
    report = audit_total_directions(json.loads(args.screen.read_text(encoding="utf-8")))
    result = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result, encoding="utf-8")
    else:
        print(result, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
