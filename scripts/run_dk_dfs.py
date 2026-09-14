#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date, datetime, time
import json
import re
from zoneinfo import ZoneInfo

from sportsedge.dfs.engine import DfsEngine


def parse_requested_start(value: str, *, slate_date: str | None, timezone_name: str) -> datetime:
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = None
    if parsed is not None and parsed.tzinfo is not None:
        return parsed

    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*([AaPp][Mm])?\s*", text)
    if not match:
        raise ValueError("--start must be timezone-aware ISO-8601 or a clock time such as 19:10 / 7:10PM")
    hour, minute = int(match.group(1)), int(match.group(2))
    meridiem = (match.group(3) or "").upper()
    if minute > 59:
        raise ValueError("invalid minute")
    if meridiem:
        if hour < 1 or hour > 12:
            raise ValueError("12-hour clock hour must be 1..12")
        hour = hour % 12 + (12 if meridiem == "PM" else 0)
    elif hour > 23:
        raise ValueError("24-hour clock hour must be 0..23")
    tz = ZoneInfo(timezone_name)
    day = date.fromisoformat(slate_date) if slate_date else datetime.now(tz).date()
    return datetime.combine(day, time(hour, minute), tzinfo=tz)


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve a DraftKings Classic slate and build one SportsEdge single-entry DFS lineup.")
    parser.add_argument("--sport", required=True, choices=("MLB", "NFL", "CFB"))
    parser.add_argument("--start", required=True, help="Slate start: timezone-aware ISO-8601, 19:10, or 7:10PM")
    parser.add_argument("--date", help="YYYY-MM-DD when --start is a clock time; defaults to today in --timezone")
    parser.add_argument("--timezone", default="America/Chicago", help="IANA zone for clock-only --start values")
    parser.add_argument("--projections", help="SportsEdge DFS projection snapshot JSON")
    parser.add_argument("--dk-salaries", help="Official DKSalaries.csv fallback when live DK acquisition is unavailable")
    parser.add_argument("--allow-dk-fppg-baseline", action="store_true", help="Emergency baseline only; not a validated SportsEdge projection model")
    parser.add_argument("--no-auto-context", action="store_true", help="Disable live lineup/injury/game-status context (debug/backtest only)")
    parser.add_argument("--allow-context-failure", action="store_true", help="Continue if live context acquisition fails; diagnostics will mark the failure")
    parser.add_argument("--beam-width", type=int, default=30000)
    parser.add_argument("--max-projection-age-hours", type=float, default=36.0)
    args = parser.parse_args()
    try:
        requested = parse_requested_start(args.start, slate_date=args.date, timezone_name=args.timezone)
    except (ValueError, KeyError) as exc:
        raise SystemExit(str(exc)) from exc
    result = DfsEngine().run(
        sport=args.sport,
        requested_start=requested,
        projection_snapshot=args.projections,
        salary_csv=args.dk_salaries,
        allow_dk_fppg_baseline=args.allow_dk_fppg_baseline,
        beam_width=args.beam_width,
        max_projection_age_hours=args.max_projection_age_hours,
        auto_context=not args.no_auto_context,
        allow_context_failure=args.allow_context_failure,
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
