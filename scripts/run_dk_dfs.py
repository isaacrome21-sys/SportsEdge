#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
import json

from sportsedge.dfs.engine import DfsEngine


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve a DraftKings Classic slate and build one SportsEdge single-entry DFS lineup.")
    parser.add_argument("--sport", required=True, choices=("MLB", "NFL", "CFB"))
    parser.add_argument("--start", required=True, help="Timezone-aware ISO-8601 slate start, e.g. 2026-09-18T19:30:00-04:00")
    parser.add_argument("--projections", help="SportsEdge DFS projection snapshot JSON")
    parser.add_argument("--dk-salaries", help="Official DKSalaries.csv fallback when live DK acquisition is unavailable")
    parser.add_argument("--allow-dk-fppg-baseline", action="store_true", help="Emergency baseline only; not a validated SportsEdge projection model")
    parser.add_argument("--beam-width", type=int, default=30000)
    parser.add_argument("--max-projection-age-hours", type=float, default=36.0)
    args = parser.parse_args()
    requested = datetime.fromisoformat(args.start)
    if requested.tzinfo is None:
        raise SystemExit("--start must include a timezone offset")
    result = DfsEngine().run(
        sport=args.sport,
        requested_start=requested,
        projection_snapshot=args.projections,
        salary_csv=args.dk_salaries,
        allow_dk_fppg_baseline=args.allow_dk_fppg_baseline,
        beam_width=args.beam_width,
        max_projection_age_hours=args.max_projection_age_hours,
    )
    print(f"{result.sport} DK Classic | draftGroup={result.slate.draft_group_id} | lock={result.slate.start_time.isoformat()}")
    for entry in result.lineup.entries:
        p, pr = entry.player, entry.projection
        own = "?" if pr.ownership is None else f"{pr.ownership:.1%}"
        print(f"{entry.slot:9s} {p.name:28s} {p.team:5s} ${p.salary:5d}  mean={pr.mean:5.2f} ceil={pr.ceiling:5.2f} own={own}  [{pr.source}]")
    print(f"salary=${result.lineup.salary} mean={result.lineup.projected_points:.2f} ceiling={result.lineup.ceiling:.2f} corr={result.lineup.correlation_score:.2f}")
    print(json.dumps(result.diagnostics, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
