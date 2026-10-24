#!/usr/bin/env python3
"""CFB Form 2 slate capture orchestrator (t271; RESEARCH ONLY).

Operator-invoked, pre-kickoff step that produces the externally pinned
QB_IDENTITY_EVIDENCE Form 2 archive the RUN IT loader consumes
(``--form2-bundles-dir`` + ``--form2-manifest-sha256``). It adds NO new
evidence rule: every bundle is built by the existing capture helper
(``qb_identity_evidence.capture_form2_bundle``), preserved by the
existing write-once archive writer, and sealed by the existing sealer.
The Form 2 gate, evaluator and loader are untouched.

What this module adds is only the per-slate plumbing the helper
requires and previously had to be typed by hand per team:

  * the fixture binding (event ID, both ESPN team IDs, kickoff) taken
    verbatim from the ESPN public scoreboard event;
  * the team's previous completed game kickoff, taken from the ESPN
    public team schedule (latest event marked completed strictly before
    the fixture kickoff; none -> PREVIOUS_GAME_UNKNOWN refusal);
  * the OurLads depth-chart URL, resolved from the OurLads public index
    by exact normalized school name, or by a small reviewed alias table
    keyed by ESPN team ID for schools whose names differ between the
    two publishers. Zero matches or more than one match refuses the
    team (OURLADS_TEAM_UNRESOLVED / OURLADS_TEAM_AMBIGUOUS). Nothing is
    guessed or fuzzy-matched; and the evaluator still has to resolve the
    chart's QB1 to exactly one QB athlete on the ESPN roster.

Fail-closed: any per-team failure is recorded as REFUSED with the named
reason and that team simply gets no bundle (its fixture then blocks at
the unchanged gate). Games at/after kickoff are never captured
(KICKOFF_PASSED_NO_BACKFILL). Output is SCREEN / NOT_VALIDATED,
play_allowed=false; no probability, price or availability is produced.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone

from artifacts.free_models import dt
from sportsedge.prepricing import qb_evidence_archive as _archive
from sportsedge.prepricing import qb_identity_evidence as _qe

OURLADS_INDEX_URL = "https://www.ourlads.com/ncaa-football-depth-charts/"
OURLADS_CHART_URL = ("https://www.ourlads.com/ncaa-football-depth-charts/"
                     "depth-chart.aspx?s={slug}&id={oid}")
ESPN_SCOREBOARD_URL = ("https://site.api.espn.com/apis/site/v2/sports/football/"
                       "college-football/scoreboard?dates={date}&groups=80&limit=300")
ESPN_SCHEDULE_URL = ("https://site.api.espn.com/apis/site/v2/sports/football/"
                     "college-football/teams/{team_id}/schedule")

# ESPN team ID -> OurLads index name, only where the publishers' school
# names differ. Each entry is a fact checkable on both public sites.
ESPN_ID_TO_OURLADS_NAME = {
    "2116": "Central Florida",      # ESPN "UCF"
    "193": "Miami (Ohio)",          # ESPN "Miami (OH)"
    "2433": "Louisiana-Monroe",     # ESPN "UL Monroe"
    "145": "Mississippi",           # ESPN "Ole Miss"
    "41": "Connecticut",            # ESPN "UConn"
    "2229": "Florida International",  # ESPN "FIU"
}

_INDEX_RE = re.compile(
    r"<div class='nfl-dc-mm-team-name'>([^<]*)</div></div>"
    r"<div class='ncaa-dc-mm-team-links'><a href='depth-chart\.aspx\?s=([a-z0-9-]+)&id=(\d+)'")


def _norm(text):
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", text.lower())


def parse_ourlads_index(html_text):
    return [(name.strip(), slug, oid) for name, slug, oid in _INDEX_RE.findall(html_text or "")]


def resolve_ourlads_url(espn_team, index):
    target = ESPN_ID_TO_OURLADS_NAME.get(str(espn_team.get("id")),
                                         espn_team.get("location"))
    hits = {(s, o) for n, s, o in index if _norm(n) == _norm(target)}
    if not hits:
        raise ValueError(f"OURLADS_TEAM_UNRESOLVED:{espn_team.get('location')}")
    if len(hits) > 1:
        raise ValueError(f"OURLADS_TEAM_AMBIGUOUS:{espn_team.get('location')}")
    slug, oid = next(iter(hits))
    return OURLADS_CHART_URL.format(slug=slug, oid=oid)


def _iso(value):
    parsed = dt(value) if not isinstance(value, datetime) else value
    if parsed is None:
        raise ValueError("TIMESTAMP_UNPARSEABLE")
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def previous_completed_kickoff(schedule_json, kickoff_utc):
    start = dt(_iso(kickoff_utc))
    best = None
    for ev in (schedule_json or {}).get("events") or []:
        try:
            done = ev["competitions"][0]["status"]["type"].get("completed") is True
            when = dt(_iso(ev["date"]))
        except (KeyError, IndexError, TypeError, AttributeError, ValueError):
            continue
        if done and when is not None and when < start and (best is None or when > best):
            best = when
    if best is None:
        raise ValueError("PREVIOUS_GAME_UNKNOWN")
    return _iso(best)


def _default_fetch_text(url):
    return _qe._fetch_text(url)


def capture_slate(events, archive_root, *, ourlads_index_html, fetch_json=None,
                  capture=None, now=None):
    """Capture/preserve/seal Form 2 bundles for every team of ``events``."""
    fetch_json = fetch_json or (lambda u: json.loads(_default_fetch_text(u)))
    capture = capture or _qe.capture_form2_bundle
    now = now or datetime.now(timezone.utc)
    index = parse_ourlads_index(ourlads_index_html)
    teams, manifests = [], []
    for ev in events:
        comp = ev["competitions"][0]
        sides = {c["homeAway"]: c["team"] for c in comp["competitors"]}
        home, away = sides["home"], sides["away"]
        kickoff = _iso(ev["date"])
        for team, opp in ((away, home), (home, away)):
            rec = {"event_id": str(ev["id"]), "team_id": str(team["id"]),
                   "team": team.get("displayName") or team.get("location"),
                   "opponent_id": str(opp["id"]), "kickoff_utc": kickoff}
            teams.append(rec)
            if dt(kickoff) <= now:
                rec.update(status="REFUSED", reason="KICKOFF_PASSED_NO_BACKFILL")
                continue
            try:
                url = resolve_ourlads_url(team, index)
                prev = previous_completed_kickoff(
                    fetch_json(ESPN_SCHEDULE_URL.format(team_id=team["id"])), kickoff)
                bundle = capture(team_id=str(team["id"]), team_name=rec["team"],
                                 event_id=str(ev["id"]), opponent_id=str(opp["id"]),
                                 kickoff_utc=kickoff, previous_game_kickoff_utc=prev,
                                 depth_url=url)
                raw = json.dumps(bundle, sort_keys=True).encode()
                kept = _archive.preserve_form2_bundle(
                    archive_root, bundle_bytes=raw, team_id=str(team["id"]),
                    event_id=str(ev["id"]), home_team_id=str(home["id"]),
                    away_team_id=str(away["id"]), kickoff=kickoff,
                    previous_game_kickoff=prev)
            except Exception as exc:  # fail closed per team, never the slate
                rec.update(status="REFUSED", reason=str(exc) or type(exc).__name__)
                continue
            manifests.append(kept["candidate_manifest_sha256"])
            rec.update(status="PRESERVED", depth_url=url, previous_game_kickoff_utc=prev,
                       bundle_sha256=kept["bundle_sha256"],
                       qb1=(bundle.get("depth_snapshot") or {}).get("qb_order", [{}])[0].get("name")
                       if isinstance(bundle.get("depth_snapshot"), dict) else None)
    pin = None
    seal_error = None
    if manifests:
        try:
            pin = _archive.seal_form2_archive_manifest(
                archive_root, manifest_sha256s=manifests)["candidate_manifest_sha256"]
        except Exception as exc:
            seal_error = str(exc)
    return {"schema": "SPORTSEDGE_CFB_FORM2_SLATE_CAPTURE_V1",
            "status_label": "SCREEN", "validation": "NOT_VALIDATED",
            "play_allowed": False, "research_only": True,
            "manifest_sha256": pin, "seal_error": seal_error,
            "anchor_status": "UNANCHORED_OPERATOR_PIN", "teams": teams}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--date", required=True, help="YYYYMMDD (ESPN scoreboard date)")
    p.add_argument("--archive", required=True, help="existing operator directory")
    p.add_argument("--event-ids", default="", help="comma list to restrict")
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    fetch_json = lambda u: json.loads(_default_fetch_text(u))
    events = fetch_json(ESPN_SCOREBOARD_URL.format(date=a.date)).get("events") or []
    if a.event_ids:
        keep = set(a.event_ids.split(","))
        events = [e for e in events if str(e.get("id")) in keep]
    rep = capture_slate(events, a.archive,
                        ourlads_index_html=_default_fetch_text(OURLADS_INDEX_URL),
                        fetch_json=fetch_json)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1)
    n = sum(t["status"] == "PRESERVED" for t in rep["teams"])
    print(f"PRESERVED {n}/{len(rep['teams'])} manifest={rep['manifest_sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
