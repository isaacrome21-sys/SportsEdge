#!/usr/bin/env python3
"""Acquire ESPN CFB season history (scoreboards, summaries, FBS list,
passer gamelogs) into checksummed bundles + manifest. Staging only.

Usage: python scripts/acquire_espn_cfb_history.py --season 2024 --out DIR [--gamelogs]
Exit: 0 COMPLETE, 3 INCOMPLETE (written anyway, gaps on the record).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sportsedge import espn_cfb_history as ec  # noqa: E402

HEADERS = {"User-Agent": "SportsEdge-free-research/1.0 (GitHub Actions)",
           "Accept": "application/json"}


def raw_fetch(url: str) -> bytes:
    with urlopen(Request(url, headers=HEADERS), timeout=30) as resp:
        return resp.read()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--gamelogs", action="store_true",
                    help="also fetch passer athlete gamelogs for this season")
    a = ap.parse_args(argv)
    out = Path(a.out) / str(a.season)
    out.mkdir(parents=True, exist_ok=True)
    fetch = ec.RateLimitedFetcher(raw_fetch)

    boards, bf = ec.acquire(ec.scoreboard_urls(a.season), fetch)
    events = ec.completed_events(json.loads(r["body"]) for r in boards)
    summaries, sf = ec.acquire([ec.summary_url(e) for e in sorted(events, key=int)], fetch)
    fbs, ff = ec.acquire([ec.fbs_teams_url(a.season)], fetch)
    fbs_ids = ec.fbs_team_ids(json.loads(fbs[0]["body"])) if fbs else []
    logs, lf = [], []
    if a.gamelogs:
        ids = ec.passer_ids(json.loads(r["body"]) for r in summaries)
        logs, lf = ec.acquire([ec.gamelog_url(i, a.season) for i in ids], fetch)
    failures = bf + sf + ff + lf
    bundles = {
        "scoreboards.jsonl.gz": ec.write_bundle(str(out / "scoreboards.jsonl.gz"), boards),
        "summaries.jsonl.gz": ec.write_bundle(str(out / "summaries.jsonl.gz"), summaries),
        "fbs_teams.jsonl.gz": ec.write_bundle(str(out / "fbs_teams.jsonl.gz"), fbs),
    }
    if a.gamelogs:
        bundles["passer_gamelogs.jsonl.gz"] = ec.write_bundle(
            str(out / "passer_gamelogs.jsonl.gz"), logs)
    summ_events = {r["url"].rsplit("event=", 1)[1] for r in summaries}
    comp = ec.completeness(events, summ_events, failures, len(fbs_ids) if fbs else None)
    run = {"run_id": os.environ.get("GITHUB_RUN_ID", "local"),
           "head_sha": os.environ.get("GITHUB_SHA", "local"),
           "finished_at_utc": datetime.now(timezone.utc).isoformat()}
    man = ec.manifest(a.season, bundles,
                      {"scoreboards": len(boards), "summaries": len(summaries),
                       "fbs_teams": len(fbs_ids), "passer_gamelogs": len(logs)},
                      comp, failures, run)
    (out / "manifest.json").write_text(json.dumps(man, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"season": a.season, "status": comp["status"],
                      "events": len(events), "fbs": len(fbs_ids),
                      "failures": len(failures)}))
    return 0 if comp["status"] == "COMPLETE" else 3


if __name__ == "__main__":
    raise SystemExit(main())
