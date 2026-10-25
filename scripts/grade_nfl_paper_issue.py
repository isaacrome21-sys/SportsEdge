#!/usr/bin/env python3
"""Grade previously captured NFL PAPER picks from an authenticated final receipt.

No sportsbook or scores are fetched by this CLI. A separate collector must
supply a final-score receipt with source URL, fetched_at and raw-body SHA256.
Missing/distinct-close evidence produces named no-CLV statuses, never a zero.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sportsedge.line_snapshots import SNAPSHOT_ROOT, load_snapshots
from sportsedge.nfl_paper_grader import NflPaperError, grade_nfl_issue

SCHEMA = "sportsedge.nfl_paper_grade.v1"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--issue", type=int, required=True)
    ap.add_argument("--final-receipt", type=Path, required=True)
    ap.add_argument("--snapshot-root", type=Path, default=SNAPSHOT_ROOT)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        final = json.loads(args.final_receipt.read_text(encoding="utf-8"))
        snaps = load_snapshots("nfl", args.issue, args.snapshot_root)
        if not snaps:
            raise NflPaperError("NFL_NO_SNAPSHOT")
        rows = grade_nfl_issue(snaps, final)
        if not rows:
            raise NflPaperError("NFL_NO_GRADEABLE_PAPER_ROWS")
    except (OSError, ValueError, TypeError, KeyError, NflPaperError) as exc:
        print(f"NFL_PAPER_GRADE_REFUSED:{exc}", file=sys.stderr)
        return 2
    result = {
        "schema": SCHEMA,
        "issue": args.issue,
        "graded_at": datetime.now(timezone.utc).isoformat(),
        "status": "PAPER",
        "final_receipt": {
            "url": final["url"], "fetched_at": final["fetched_at"],
            "sha256": final["sha256"],
        },
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(f"NFL_PAPER_GRADED issue={args.issue} rows={len(rows)} -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
