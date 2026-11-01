"""Run CAPPER_VETTER_V1 end to end.

  gh issues "[CAPPER] ..."  ->  pick records  ->  ESPN scoreboard (tip time,
  DK close, final score)  ->  grades  ->  artifacts/capper_vetter/
  {picks.jsonl, rankings.json, rankings.md}  ->  optional comment on the
  "[CAPPER RANKINGS]" tracker issue.

Free sources only: GitHub CLI (workflow token) and ESPN's public scoreboard.
Writes nothing into the repository.

  python scripts/run_capper_vetter.py [--post] [--issues-json FILE] [--offline]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sportsedge.capper_pipeline import (  # noqa: E402
    CT, ESPN_PATHS, PickParseError, attach_close, event_tip, match_event,
    parse_issue, render_table, scoreboard_dates, settle,
)
from sportsedge.capper_vetter import load_config, rank  # noqa: E402

OUT = Path("artifacts/capper_vetter")
TRACKER_TITLE = "[CAPPER RANKINGS]"


def gh_json(args: list[str]):
    return json.loads(subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout)


def load_issues(path: str | None) -> list[dict]:
    if path:
        return json.loads(Path(path).read_text())
    issues = gh_json(["issue", "list", "--state", "all", "--limit", "1000",
                      "--search", "[CAPPER] in:title",
                      "--json", "number,title,body,createdAt,comments"])
    return [i for i in issues if i["title"].startswith("[CAPPER]")
            and not i["title"].startswith(TRACKER_TITLE)]


_cache: dict[tuple, list] = {}


def scoreboard(sport: str, date: str) -> list[dict]:
    key = (sport, date)
    if key not in _cache:
        path, group = ESPN_PATHS[sport]
        url = (f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard"
               f"?dates={date}&limit=500" + (f"&groups={group}" if group else ""))
        req = urllib.request.Request(url, headers={"User-Agent": "SportsEdge-capper-vetter"})
        with urllib.request.urlopen(req, timeout=30) as r:
            _cache[key] = json.load(r).get("events", [])
    return _cache[key]


def build(issues: list[dict], offline: bool) -> tuple[list[dict], list[str]]:
    picks, errors, seen = [], [], {}
    for it in sorted(issues, key=lambda i: i["number"]):
        comments = [c.get("body", "") for c in it.get("comments") or []]
        try:
            p = parse_issue(it["number"], it["title"], it.get("body", ""), it.get("createdAt"), comments)
        except PickParseError as e:
            errors.append(f"#{it['number']}: {e}")
            continue
        if p.get("void"):
            continue
        key = (p["account"].lower(), p["away"].lower(), p["home"].lower(), p["market"],
               p["selection"].lower(), p["line"])
        if key in seen:
            errors.append(f"#{it['number']}: duplicate of #{seen[key]}")
            continue
        seen[key] = it["number"]
        if not offline:
            ev = None
            try:
                for d in scoreboard_dates(p):
                    ev = match_event(p, scoreboard(p["sport"], d))
                    if ev:
                        break
            except Exception as e:  # network/provider failure: keep pick, mark untimed
                errors.append(f"#{it['number']}: scoreboard unavailable ({e.__class__.__name__}); kept as untimed")
            if ev:
                p["espn_event_id"] = ev.get("id")
                p["tip_utc"] = event_tip(ev).astimezone(timezone.utc).isoformat()
                try:
                    attach_close(p, ev)
                    settle(p, ev)
                except PickParseError as e:
                    errors.append(f"#{it['number']}: {e}")
            elif "espn_event_id" not in p:
                errors.append(f"#{it['number']}: no {p['sport']} game found for {p['away']} @ {p['home']}")
        picks.append(p)
    return picks, errors


def post(markdown: str) -> None:
    found = gh_json(["issue", "list", "--state", "open", "--search", f"{TRACKER_TITLE} in:title",
                     "--json", "number,title"])
    num = next((i["number"] for i in found if i["title"].startswith(TRACKER_TITLE)), None)
    body = OUT / "rankings.md"
    if num is None:
        subprocess.run(["gh", "issue", "create", "--title", f"{TRACKER_TITLE} Outside capper grades",
                        "--body-file", str(body)], check=True)
    else:
        subprocess.run(["gh", "issue", "comment", str(num), "--body-file", str(body)], check=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--post", action="store_true")
    ap.add_argument("--issues-json")
    ap.add_argument("--offline", action="store_true", help="skip ESPN (tests)")
    a = ap.parse_args()
    issues = load_issues(a.issues_json)
    picks, errors = build(issues, a.offline)
    rows = rank(picks, load_config()) if picks else []
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "picks.jsonl").write_text("".join(json.dumps(p, sort_keys=True) + "\n" for p in picks))
    (OUT / "rankings.json").write_text(json.dumps(rows, indent=2))
    md = render_table(rows, len(issues), errors, datetime.now(CT).strftime("%Y-%m-%d %I:%M %p CT"))
    (OUT / "rankings.md").write_text(md)
    print(md)
    if a.post:
        post(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
