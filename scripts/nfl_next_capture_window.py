#!/usr/bin/env python3
"""Report the next NFL confirmation obligation in CT without touching odds APIs."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sportsedge.nfl_public_schedule import fetch_nfl_events

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "config/nfl_2026_capture.json").read_text())
CT = ZoneInfo(CFG["timezone"])


def parse_iso(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def next_window(now=None, events=None):
    now = now or datetime.now(timezone.utc)
    lead = timedelta(minutes=CFG["final_minutes_before_kickoff"])
    width = timedelta(minutes=CFG["final_window_minutes"])
    candidates = []
    for ev in events if events is not None else fetch_nfl_events():
        kickoff = parse_iso(ev["commence_time"])
        start, deadline = kickoff - lead, kickoff - lead + width
        if deadline > now:
            candidates.append((start, deadline, ev))
    # OPENER is deterministic and remains a competing obligation.
    local = now.astimezone(CT)
    for offset in range(0, 15):
        day = local.date() + timedelta(days=offset)
        if day.strftime("%A") != CFG["opener_weekday"]:
            continue
        hh, mm = map(int, CFG["opener_local_time"].split(":"))
        start = datetime(day.year, day.month, day.day, hh, mm, tzinfo=CT).astimezone(timezone.utc)
        deadline = start + timedelta(minutes=CFG["opener_window_minutes"])
        if deadline > now:
            candidates.append((start, deadline, {"capture_kind": "OPENER"}))
            break
    if not candidates:
        return None
    start, deadline, ev = min(candidates, key=lambda x: x[0])
    if ev.get("capture_kind") == "OPENER":
        return {"capture_kind": "OPENER", "start_ct": start.astimezone(CT).isoformat(),
                "deadline_ct": deadline.astimezone(CT).isoformat(), "schedule_source": "FROZEN_CONFIG"}
    return {"capture_kind": "FINAL", "event_id": ev["id"], "away_team": ev.get("away_team"),
            "home_team": ev.get("home_team"), "kickoff_ct": parse_iso(ev["commence_time"]).astimezone(CT).isoformat(),
            "start_ct": start.astimezone(CT).isoformat(), "deadline_ct": deadline.astimezone(CT).isoformat(),
            "schedule_source": ev.get("schedule_source"), "schedule_only": True}


if __name__ == "__main__":
    print(json.dumps(next_window(), sort_keys=True))
