#!/usr/bin/env python3
"""Fetch or read nflverse games.csv, hash exact bytes, and emit a real-history audit."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sportsedge.sports.nfl.history import NFLVERSE_SCHEDULE_CSV
from sportsedge.sports.nfl.real_history_audit import audit_nfl_history_rows


def fetch_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "SportsEdge-football-validation/1.0"})
    with urlopen(request, timeout=30) as response:
        return response.read()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/football/nfl_real_history_audit.json")
    parser.add_argument("--min-season", type=int, default=1999)
    parser.add_argument("--max-season", type=int, default=2025)
    parser.add_argument("--source-file", type=Path)
    args = parser.parse_args()

    payload = args.source_file.read_bytes() if args.source_file is not None else fetch_bytes(NFLVERSE_SCHEDULE_CSV)
    source_sha256 = hashlib.sha256(payload).hexdigest()
    text = payload.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    rows = [
        row for row in rows
        if row.get("season") and args.min_season <= int(row["season"]) <= args.max_season
    ]
    report = audit_nfl_history_rows(
        rows,
        source_url=NFLVERSE_SCHEDULE_CSV,
        source_sha256=source_sha256,
    )
    report["requested_season_range"] = [args.min_season, args.max_season]
    report["source_transport"] = "FROZEN_LOCAL_BYTES" if args.source_file is not None else "LIVE_FETCH"

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
