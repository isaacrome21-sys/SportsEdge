#!/usr/bin/env python3
"""Free StatsAPI gate for bounded automated MLB postseason paid runs."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Callable
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sportsedge.mlb_source import fetch_schedule, parse_game_start  # noqa: E402

CHICAGO_TZ = ZoneInfo("America/Chicago")
DEFAULT_START = date(2026, 9, 29)
DEFAULT_END = date(2026, 11, 8)
DEFAULT_MIN_LEAD_MINUTES = 45
DEFAULT_MAX_LEAD_MINUTES = 75


def evaluate_postseason_gate(*, now: datetime, start_date: date = DEFAULT_START,
                             end_date: date = DEFAULT_END,
                             min_lead_minutes: int = DEFAULT_MIN_LEAD_MINUTES,
                             max_lead_minutes: int = DEFAULT_MAX_LEAD_MINUTES,
                             fetcher: Callable = fetch_schedule) -> dict:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if min_lead_minutes < 0 or max_lead_minutes <= min_lead_minutes:
        raise ValueError("invalid lead window")
    current = now.astimezone(timezone.utc)
    slate_date = current.astimezone(CHICAGO_TZ).date()
    if slate_date < start_date or slate_date > end_date:
        return {
            "active_window": False,
            "due": False,
            "slate_date_ct": slate_date.isoformat(),
            "due_game_pks": [],
            "reason": "OUTSIDE_2026_POSTSEASON_WINDOW",
        }

    schedule = fetcher(slate_date.isoformat(), now=current)
    due = []
    for game in schedule:
        if str(getattr(game, "status", "")) != "Preview":
            continue
        start = parse_game_start(game.game_date)
        lead = (start - current).total_seconds() / 60.0
        if min_lead_minutes <= lead < max_lead_minutes:
            due.append(int(game.game_pk))
    return {
        "active_window": True,
        "due": bool(due),
        "slate_date_ct": slate_date.isoformat(),
        "due_game_pks": sorted(due),
        "reason": "PREGAME_CLUSTER_DUE" if due else "NO_GAME_IN_PAID_WINDOW",
        "lead_window_minutes": [min_lead_minutes, max_lead_minutes],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-date", default=DEFAULT_START.isoformat())
    ap.add_argument("--end-date", default=DEFAULT_END.isoformat())
    ap.add_argument("--min-lead-minutes", type=int, default=DEFAULT_MIN_LEAD_MINUTES)
    ap.add_argument("--max-lead-minutes", type=int, default=DEFAULT_MAX_LEAD_MINUTES)
    ap.add_argument("--now", help="UTC/offset-aware ISO timestamp override for tests")
    args = ap.parse_args(argv)
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(timezone.utc)
    result = evaluate_postseason_gate(
        now=now,
        start_date=date.fromisoformat(args.start_date),
        end_date=date.fromisoformat(args.end_date),
        min_lead_minutes=args.min_lead_minutes,
        max_lead_minutes=args.max_lead_minutes,
    )
    print(json.dumps(result, sort_keys=True))
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as fh:
            fh.write(f"due={'true' if result['due'] else 'false'}\n")
            fh.write(f"slate_date_ct={result['slate_date_ct']}\n")
            fh.write("due_game_pks=" + ",".join(str(x) for x in result["due_game_pks"]) + "\n")
            fh.write(f"reason={result['reason']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
