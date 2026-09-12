#!/usr/bin/env python3
"""Audit two immutable CFB forward-market snapshots as an exact pair."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.cfb.forward_market_pairing import pair_snapshots  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--decision-dir", type=Path, required=True)
    parser.add_argument("--close-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = pair_snapshots(args.decision_dir, args.close_dir)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "PAIRED_FORWARD_MARKET_EVIDENCE_AVAILABLE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
