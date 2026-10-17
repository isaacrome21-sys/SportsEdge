#!/usr/bin/env python3
"""Acquire MLB StatsAPI season history into deterministic, checksummed
bundles + a manifest (see sportsedge/statsapi_history.py for the contract).

Usage: python scripts/acquire_statsapi_history.py --season 2026 --out DIR
Exit codes: 0 = COMPLETE, 3 = INCOMPLETE (bundles + manifest still written
so the gaps are on the record), 2 = usage/transport setup error.
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
from sportsedge import statsapi_history as sh  # noqa: E402

HEADERS = {"User-Agent": "SportsEdge-free-research/1.0 (GitHub Actions)",
           "Accept": "application/json"}


def raw_fetch(url: str) -> bytes:
    with urlopen(Request(url, headers=HEADERS), timeout=30) as resp:
        return resp.read()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--months", default="3,4,5,6,7,8,9,10")
    args = ap.parse_args(argv)
    out = Path(args.out) / str(args.season)
    out.mkdir(parents=True, exist_ok=True)
    fetch = sh.RateLimitedFetcher(raw_fetch)

    players, pfail = sh.acquire([sh.players_url(args.season)], fetch)
    if not players:
        print(json.dumps({"status": "INCOMPLETE", "reason": "PLAYERS_FETCH_FAILED",
                          "failures": pfail}))
        return 3
    pbody = json.loads(players[0]["body"])
    copyright_text = pbody.get("copyright")
    ids = sh.pitcher_ids(pbody)

    months = [int(m) for m in args.months.split(",")]
    sched, sfail = sh.acquire([sh.schedule_url(args.season, m) for m in months], fetch)
    logs, lfail = sh.acquire([sh.pitching_log_url(i, args.season) for i in ids], fetch)
    final_games = sh.final_regular_games(json.loads(r["body"]) for r in sched)
    hids = sh.hitter_ids(pbody)
    hlogs, hfail = sh.acquire([sh.hitting_log_url(i, args.season) for i in hids], fetch)
    boxes, bfail = sh.acquire([sh.boxscore_url(g) for g in sorted(final_games)], fetch)
    box_games = {int(r["url"].split("/game/")[1].split("/")[0]) for r in boxes}
    failures = pfail + sfail + lfail + hfail + bfail

    bundles = {
        "players.jsonl.gz": sh.write_bundle(str(out / "players.jsonl.gz"), players),
        "schedule.jsonl.gz": sh.write_bundle(str(out / "schedule.jsonl.gz"), sched),
        "pitching_gamelogs.jsonl.gz": sh.write_bundle(
            str(out / "pitching_gamelogs.jsonl.gz"), logs),
        "hitting_gamelogs.jsonl.gz": sh.write_bundle(
            str(out / "hitting_gamelogs.jsonl.gz"), hlogs),
        "boxscores.jsonl.gz": sh.write_bundle(str(out / "boxscores.jsonl.gz"), boxes),
    }
    comp = sh.completeness(
        final_games, sh.starts_by_game(json.loads(r["body"]) for r in logs), failures,
        boxscore_games=box_games)
    run = {"run_id": os.environ.get("GITHUB_RUN_ID", "local"),
           "head_sha": os.environ.get("GITHUB_SHA", "local"),
           "ref": os.environ.get("GITHUB_REF", "local"),
           "finished_at_utc": datetime.now(timezone.utc).isoformat()}
    man = sh.manifest(args.season, bundles,
                      {"players": len(players), "schedule_months": len(sched),
                       "pitching_gamelogs": len(logs), "pitchers_listed": len(ids),
                       "hitting_gamelogs": len(hlogs), "hitters_listed": len(hids),
                       "boxscores": len(boxes)},
                      comp, failures, copyright_text, run)
    (out / "manifest.json").write_text(json.dumps(man, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"season": args.season, "status": comp["status"],
                      "final_games": comp["final_regular_games"],
                      "two_starters": comp["games_with_two_starters"],
                      "failures": len(failures)}))
    return 0 if comp["status"] == "COMPLETE" else 3


if __name__ == "__main__":
    raise SystemExit(main())
