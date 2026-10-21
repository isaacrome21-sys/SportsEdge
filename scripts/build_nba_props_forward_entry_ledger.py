#!/usr/bin/env python3
"""Price a captured NBA prop board and write its prospective entry ledger."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.forward_validation.nba_full_board_ledger import (  # noqa: E402
    NbaFullBoardLedgerError,
    build_nba_props_entry_ledger,
)
from sportsedge.nba_phone_prop_pricing import phone_nba_prop_rows  # noqa: E402


def _rows(path: str) -> list[dict]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = doc if isinstance(doc, list) else doc.get("lines") or doc.get("rows")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise NbaFullBoardLedgerError("RAW_BOARD_ROWS_REQUIRED")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-board", required=True)
    ap.add_argument("--store-dir", required=True)
    ap.add_argument("--slate-date", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--source-ref", required=True)
    ap.add_argument("--recorded-at", required=True)
    ap.add_argument("--now", required=True,
                    help="timezone-aware pricing instant; should be the capture run time")
    ap.add_argument("--min-ev", type=float, default=0.02)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    try:
        now = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError
    except ValueError:
        print("NOW_TIMEZONE_REQUIRED", file=sys.stderr)
        return 2
    try:
        raw = _rows(args.raw_board)
        priced, receipts = phone_nba_prop_rows(
            raw, now=now, store_dir=args.store_dir, min_ev=args.min_ev
        )
        result = build_nba_props_entry_ledger(
            raw, priced, run_id=args.run_id, source_ref=args.source_ref,
            recorded_at=args.recorded_at, slate_date=args.slate_date,
        )
        result["pricing_receipts"] = receipts
    except (OSError, json.JSONDecodeError, NbaFullBoardLedgerError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(json.dumps({"out": str(out), "status": result["status"],
                      "accounting": result["accounting"],
                      "ledger_sha256": result["ledger_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
