"""Print reproducible DK route gaps from an explicit census path.

Usage:
  python -m sportsedge.dk_route_gap_cli config/dk_inspected_menu_census_v1.json

Research-only. Never fetches quotes, activates capture or prices markets.
"""
from __future__ import annotations

import argparse
import json

from sportsedge.dk_route_gap_report import build_route_gap_report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("census", help="Path to an inspected DK menu census JSON")
    args = parser.parse_args(argv)
    report = build_route_gap_report(args.census)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
