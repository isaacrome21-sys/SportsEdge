#!/usr/bin/env python3
"""[NFL LINES] ticket -> canonical RUN IT (artifacts/run_it_full.py) -> props card.

Fail closed: no independent kickoff -> that game's props are not priced.
The pricing clock is the run time passed by the workflow (--as-of), so the
180 s quote freshness bound measures real age.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sportsedge.nfl_props_card import render_props_card, ticket_to_run_it_lines  # noqa: E402


def kickoffs_from_schedule(schedule: list, games: list) -> dict[str, str]:
    from sportsedge.nfl_team_aliases import NflTeamAliasError, resolve_team

    def code(name):
        try:
            return resolve_team(str(name or ""))
        except NflTeamAliasError:
            return None

    out = {}
    for g in games:
        hits = [r for r in schedule or [] if isinstance(r, dict)
                and code(r.get("away_team")) == g.get("away")
                and code(r.get("home_team")) == g.get("home")]
        if len(hits) == 1 and hits[0].get("commence_time"):
            out[f"{g['away']}@{g['home']}"] = str(hits[0]["commence_time"])
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="intake ticket JSON (scripts/intake_nfl_lines_issue.py)")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--as-of", default="", help="pricing clock; default now")
    ap.add_argument("--schedule", default="", help="schedule JSON (fetch_nfl_events rows)")
    ap.add_argument("--fetch-espn-schedule", action="store_true")
    args = ap.parse_args(argv)
    ticket = json.loads(Path(args.input).read_text(encoding="utf-8"))
    games = ticket.get("games") or []
    schedule: list = []
    if args.schedule:
        schedule = json.loads(Path(args.schedule).read_text(encoding="utf-8"))
    elif args.fetch_espn_schedule:
        try:
            from sportsedge.nfl_public_schedule import fetch_nfl_events
            schedule = fetch_nfl_events()
        except Exception:  # noqa: BLE001 - fail closed: no kickoff, no pricing
            schedule = []
    lines, notes = ticket_to_run_it_lines(ticket, kickoffs_from_schedule(schedule, games))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "run_it_lines.json").write_text(json.dumps({"sport": "NFL", "lines": lines}, indent=2), encoding="utf-8")
    title = " · ".join(f"{g.get('away')} @ {g.get('home')}" for g in games[:3]) or "no games"
    if not lines:
        card = {"evaluated_rows": []}
    else:
        from artifacts.run_it_full import run_full
        as_of = args.as_of or datetime.now(timezone.utc).isoformat()
        card = run_full({"sport": "NFL", "lines": lines}, as_of=as_of)
        (out / "run_it_card.json").write_text(json.dumps(card, indent=2, default=str), encoding="utf-8")
    (out / "props_card.md").write_text(render_props_card(card, title=title, notes=notes), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
