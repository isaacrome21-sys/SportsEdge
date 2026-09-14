#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from sportsedge.dfs.ownership_evidence import ingest_standings_csv, write_immutable_evidence


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Freeze post-contest DraftKings standings ownership evidence."
    )
    parser.add_argument("--sport", required=True, choices=("MLB", "NFL", "CFB"))
    parser.add_argument("--standings", required=True, help="DraftKings post-contest standings CSV")
    parser.add_argument("--contest-id", required=True)
    parser.add_argument("--contest-name", default="")
    parser.add_argument("--draft-group-id", default="")
    parser.add_argument("--slate-start", help="Timezone-aware ISO-8601 slate lock/start")
    parser.add_argument("--output", required=True, help="New immutable JSON evidence path")
    args = parser.parse_args()

    slate_start = datetime.fromisoformat(args.slate_start) if args.slate_start else None
    if slate_start is not None and slate_start.tzinfo is None:
        raise SystemExit("--slate-start must include a timezone offset")
    raw = Path(args.standings).read_bytes()
    evidence = ingest_standings_csv(
        raw,
        sport=args.sport,
        contest_id=args.contest_id,
        contest_name=args.contest_name,
        draft_group_id=args.draft_group_id,
        slate_start=slate_start,
    )
    path = write_immutable_evidence(evidence, args.output)
    print(
        f"frozen {evidence.sport} contest={evidence.contest_id} "
        f"entries={evidence.valid_entries} players={evidence.player_count} "
        f"sha256={evidence.source_sha256} -> {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
