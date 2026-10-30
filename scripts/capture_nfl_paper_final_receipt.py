#!/usr/bin/env python3
"""Fetch exact ESPN NFL final for an existing issue snapshot; save immutable receipt.

Example:
  python scripts/capture_nfl_paper_final_receipt.py --issue 1234 \
    --out ledger/nfl_final_receipts/1234.json

The receipt is result evidence, not a quote. No finalized match => refusal.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sportsedge.line_snapshots import SNAPSHOT_ROOT, load_snapshots
from sportsedge.nfl_final_receipts import FinalReceiptError, fetch_espn_final_with_bytes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue", required=True, type=int)
    parser.add_argument("--snapshot-root", type=Path, default=SNAPSHOT_ROOT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        snapshots = load_snapshots("nfl", args.issue, args.snapshot_root)
        fixtures = {
            (s["game"]["away"], s["game"]["home"], s["game"]["start"])
            for s in snapshots
        }
        if len(fixtures) != 1:
            raise FinalReceiptError("FINAL_ONE_CAPTURED_FIXTURE_REQUIRED")
        away, home, kickoff = next(iter(fixtures))
        receipt, raw = fetch_espn_final_with_bytes(away=away, home=home,
                                                   kickoff=kickoff)
        raw_path = Path(str(args.out) + ".raw.json")
        if args.out.exists() or raw_path.exists():
            raise FinalReceiptError("FINAL_RECEIPT_ALREADY_EXISTS")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with raw_path.open("xb") as source_file:
            source_file.write(raw)
        with args.out.open("x", encoding="utf-8") as file:
            json.dump(receipt, file, sort_keys=True, indent=2)
            file.write("\n")
    except (OSError, ValueError, TypeError, KeyError, FinalReceiptError) as exc:
        print(f"NFL_FINAL_RECEIPT_REFUSED:{exc}", file=sys.stderr)
        return 2
    print(f"NFL_FINAL_RECEIPT_SAVED issue={args.issue} event={receipt['event_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
