#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.mlb.the_odds_api_pairing import audit_snapshot_pair  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit two immutable The Odds API MLB historical snapshots as a decision/close pair.")
    ap.add_argument("--decision-dir", type=Path, required=True)
    ap.add_argument("--close-dir", type=Path, required=True)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    report = audit_snapshot_pair(args.decision_dir, args.close_dir)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "READY_FOR_REPLAY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
