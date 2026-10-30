#!/usr/bin/env python3
"""Record a strictly timed NFL PAPER issue snapshot from independent card data.

Never uses GitHub issue created_at/updated_at as a quote capture or kickoff.
The card JSON must carry a unique kickoff obtained from public schedule data.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sportsedge.nfl_paper_grader import NflPaperError, capture_nfl_issue
from sportsedge.nfl_lines_intake import NflLinesIntakeError
from sportsedge.line_snapshots import SNAPSHOT_ROOT, SnapshotError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--body-file", type=Path, required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--issue", type=int, required=True)
    parser.add_argument("--engine-json", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=SNAPSHOT_ROOT)
    args = parser.parse_args(argv)

    try:
        card = json.loads(args.engine_json.read_text(encoding="utf-8"))
        games = card.get("games") or []
        if len(games) != 1 or not games[0].get("commence_time"):
            raise NflPaperError("NFL_INDEPENDENT_KICKOFF_UNAVAILABLE")
        snap = capture_nfl_issue(
            body=args.body_file.read_text(encoding="utf-8"),
            title=args.title,
            issue_number=args.issue,
            game_start=games[0]["commence_time"],
            recorded_at=datetime.now(timezone.utc).isoformat(),
            engine=card,
            root=args.root,
        )
    except (OSError, ValueError, KeyError, TypeError, NflPaperError,
            NflLinesIntakeError, SnapshotError) as exc:
        print(f"NFL_PAPER_CAPTURE_REFUSED:{exc}", file=sys.stderr)
        return 2

    print(json.dumps({
        "status": "NFL_PAPER_SNAPSHOT_RECORDED",
        "issue": args.issue,
        "captured_at": snap["captured_at"],
        "recorded_at": snap["recorded_at"],
        "picks": len(snap["picks"]),
        "ladder": "PAPER",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
