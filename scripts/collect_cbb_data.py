#!/usr/bin/env python3
"""Collect one CBB research season file into a local archive (research only).

Free public sources -- no key, no account: SportsDataverse GitHub
releases (ESPN and NCAA men's college basketball play-by-play) and
BartTorvik's published T-Rank season CSV. Each download lands in the
archive with a sha256 manifest carrying provenance. It is never a
pricing input and no CBB engine consumes it yet:
see sportsedge/cbb_data_sources.py and
docs/cbb_data_feed_research_20261024.md.

Examples:
  python3 scripts/collect_cbb_data.py --source torvik_team_ratings --season 2027
  python3 scripts/collect_cbb_data.py --source ncaa_mbb_pbp --season 2026
  python3 scripts/collect_cbb_data.py --source espn_mbb_pbp --season 2026 \
      --archive-dir artifacts/cbb_data

Exit 0 with the manifest printed; exit 2 on source/contract failure,
with nothing fabricated and no partial file left in the archive.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sportsedge.cbb_data_sources import (  # noqa: E402
    CBBDataSourceError, SOURCES, collect,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", required=True, choices=sorted(SOURCES))
    ap.add_argument("--season", required=True, type=int)
    ap.add_argument(
        "--archive-dir", type=Path, default=Path("artifacts/cbb_data"),
        help="research archive root (default: artifacts/cbb_data)",
    )
    args = ap.parse_args()
    try:
        manifest = collect(args.source, args.season, args.archive_dir)
    except CBBDataSourceError as exc:
        print(f"COLLECT_FAILED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(manifest, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
