#!/usr/bin/env python3
"""Capture QB_IDENTITY_EVIDENCE Form 2 bundles for a whole CFB intake slate.

Runs where the network is reachable (GitHub Actions). For every CFB game in
a FREE RUN IT style lines JSON it:

  1. resolves the fixture on the ESPN scoreboard (event ID, both team IDs,
     authoritative kickoff) by pairing BOTH intake team names to one event;
  2. finds each team's most recent completed game kickoff (ESPN schedule);
  3. finds the team's OurLads depth-chart URL from the OurLads index;
  4. captures the bundle with the existing receipted capture helper
     (``capture_form2_bundle``), preserves it write-once in the archive and
     finally seals ONE archive manifest over every preserved receipt.

Nothing here certifies anything. The sealed manifest digest it prints is a
CANDIDATE only: per the Form 2 contract it becomes a pricing pin only when
the operator supplies it back from an independent channel (the
``cfb-form2-slate`` workflow's price step takes it from an owner comment).
Every per-team failure is recorded with its reason and fails closed; no
bundle, kickoff or QB is invented. Kickoffs in the intake are rewritten to
the ESPN event kickoff so the loader's fixture binding matches exactly.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.prepricing.qb_identity_evidence import capture_form2_bundle  # noqa: E402
from sportsedge.prepricing.qb_evidence_archive import (  # noqa: E402
    preserve_form2_bundle, seal_form2_archive_manifest)

ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/college-football"
OURLADS_INDEX = "https://www.ourlads.com/ncaa-football-depth-charts/"
UA = {"User-Agent": "SportsEdge-CFB-Form2/1"}

# OurLads slugs that do not follow slugify(ESPN location).
OURLADS_ALIASES = {
    "miami": ["miami-fl", "miami-florida", "miami"],
    "miami oh": ["miami-oh", "miami-ohio"],
    "ucf": ["ucf", "central-florida"],
    "byu": ["byu", "brigham-young"],
    "smu": ["smu", "southern-methodist"],
    "tcu": ["tcu", "texas-christian"],
    "lsu": ["lsu", "louisiana-state"],
    "florida atlantic": ["florida-atlantic", "fau"],
    "pittsburgh": ["pittsburgh", "pitt"],
    "unlv": ["unlv", "nevada-las-vegas"],
    "usc": ["usc", "southern-california"],
}


def key(name):
    return re.sub(r"[^a-z0-9]+", " ", str(name or "").lower()).strip()


def slug(name):
    return key(name).replace(" ", "-")


def get(url):
    with urlopen(Request(url, headers=UA), timeout=45) as r:
        return r.read().decode("utf-8", "replace")


def iso_z(value):
    d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def team_keys(team):
    out = set()
    for f in ("location", "shortDisplayName", "displayName", "abbreviation", "name"):
        if team.get(f):
            out.add(key(team[f]))
    return out


def scoreboard(date):
    data = json.loads(get(f"{ESPN}/scoreboard?dates={date}&groups=80&limit=400"))
    events = []
    for ev in data.get("events", []):
        comp = ev["competitions"][0]
        sides = {c["homeAway"]: c["team"] for c in comp["competitors"]}
        events.append({"event_id": str(ev["id"]), "kickoff": iso_z(ev["date"]),
                       "home": sides["home"], "away": sides["away"]})
    return events


def previous_kickoff(team_id, before):
    data = json.loads(get(f"{ESPN}/teams/{team_id}/schedule"))
    prior = []
    for ev in data.get("events", []):
        st = ((ev.get("competitions") or [{}])[0].get("status") or {}).get("type") or {}
        when = iso_z(ev["date"])
        if st.get("completed") and when < before:
            prior.append(when)
    if not prior:
        raise ValueError("NO_PRIOR_COMPLETED_GAME")
    return max(prior)


def ourlads_index():
    html = get(OURLADS_INDEX)
    links = {}
    for s, i in re.findall(r"/ncaa-football-depth-charts/depth-chart/([a-z0-9-]+)/(\d+)", html):
        links.setdefault(s, f"{OURLADS_INDEX}depth-chart/{s}/{i}")
    return links


def ourlads_url(links, intake_name, team):
    cands = list(OURLADS_ALIASES.get(key(intake_name), []))
    cands += [slug(team.get("location")), slug(intake_name),
              slug(team.get("displayName")), slug(team.get("abbreviation"))]
    for c in cands:
        if c and c in links:
            return links[c]
    raise ValueError("OURLADS_TEAM_NOT_FOUND")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", type=Path, required=True)
    ap.add_argument("--archive", type=Path, required=True)
    ap.add_argument("--resolved-lines", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    args = ap.parse_args(argv)

    data = json.loads(args.lines.read_text(encoding="utf-8"))
    rows = data["lines"] if isinstance(data, dict) else data
    sport = (data.get("sport") if isinstance(data, dict) else None) or "CFB"
    games = {}
    for r in rows:
        if str(r.get("sport") or sport).upper() == "CFB":
            games.setdefault((r["away"], r["home"]), r)
    dates = sorted({datetime.fromisoformat(r["commence_time"]).strftime("%Y%m%d")
                    for r in games.values()})
    events = [e for d in dates for e in scoreboard(d)]
    links = ourlads_index()
    args.archive.mkdir(parents=True, exist_ok=True)

    report = {"games": [], "teams": [], "sealed_manifest_sha256": None}
    receipts, kickoff_fix = [], {}
    for (away, home), row in games.items():
        match = [e for e in events
                 if key(away) in team_keys(e["away"]) and key(home) in team_keys(e["home"])]
        if len(match) != 1:
            report["games"].append({"game": f"{away} @ {home}",
                                    "status": f"ESPN_FIXTURE_MATCHES_{len(match)}"})
            continue
        ev = match[0]
        kickoff_fix[(away, home)] = ev["kickoff"]
        report["games"].append({"game": f"{away} @ {home}", "status": "RESOLVED",
                                "event_id": ev["event_id"], "kickoff": ev["kickoff"]})
        for name, team, opp in ((away, ev["away"], ev["home"]), (home, ev["home"], ev["away"])):
            entry = {"team": name, "espn_id": str(team["id"]), "event_id": ev["event_id"]}
            try:
                prev = previous_kickoff(team["id"], ev["kickoff"])
                url = ourlads_url(links, name, team)
                bundle = capture_form2_bundle(
                    team_id=str(team["id"]), team_name=name, event_id=ev["event_id"],
                    opponent_id=str(opp["id"]), kickoff_utc=ev["kickoff"],
                    previous_game_kickoff_utc=prev, depth_url=url)
                saved = preserve_form2_bundle(
                    str(args.archive),
                    bundle_bytes=json.dumps(bundle, sort_keys=True).encode(),
                    team_id=str(team["id"]), event_id=ev["event_id"],
                    home_team_id=str(ev["home"]["id"]), away_team_id=str(ev["away"]["id"]),
                    kickoff=ev["kickoff"], previous_game_kickoff=prev)
                receipts.append(saved["candidate_manifest_sha256"])
                entry.update(status="CAPTURED", ourlads_url=url,
                             qb1=bundle["depth_snapshot"]["qb_order"][0]["name"])
            except Exception as exc:  # each team fails closed on its own
                entry.update(status="FAILED", reason=f"{type(exc).__name__}: {exc}"[:300])
            report["teams"].append(entry)

    if receipts:
        sealed = seal_form2_archive_manifest(str(args.archive), manifest_sha256s=receipts)
        report["sealed_manifest_sha256"] = sealed["candidate_manifest_sha256"]

    for r in rows:
        k = (r.get("away"), r.get("home"))
        if k in kickoff_fix:
            r["commence_time"] = kickoff_fix[k]
    out = {"sport": sport, "lines": rows} if isinstance(data, dict) else rows
    args.resolved_lines.write_text(json.dumps(out, indent=1), encoding="utf-8")
    args.report.write_text(json.dumps(report, indent=1), encoding="utf-8")
    ok = sum(t["status"] == "CAPTURED" for t in report["teams"])
    print(json.dumps({"teams_captured": ok, "teams_total": len(report["teams"]),
                      "sealed_manifest_sha256": report["sealed_manifest_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
