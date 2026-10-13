#!/usr/bin/env python3
"""Run the as-of NBA ratings harness on a local cache of free ESPN summaries.

Usage: python scripts/run_nba_asof_harness.py --cache DIR
Each file: {"id","date","teams":[{"abbr","homeAway","score","box":{...}}],"source","retrieved_at"}.
No odds, no paid calls; the cache is not committed. Research only.
"""
import argparse, json, pathlib
from datetime import datetime

from sportsedge.sports.nba.asof_team_ratings import NBAGame, possessions
from sportsedge.sports.nba.asof_harness import run_harness


def load(cache):
    out, skipped = [], 0
    for p in sorted(pathlib.Path(cache).glob("*.json")):
        d = json.loads(p.read_text())
        try:
            t = {x["homeAway"]: x for x in d["teams"]}
            g = NBAGame(str(d["id"]), datetime.fromisoformat(d["date"].replace("Z", "+00:00")),
                        t["home"]["abbr"], t["away"]["abbr"], t["home"]["score"], t["away"]["score"],
                        possessions(t["home"]["box"]), possessions(t["away"]["box"]))
            g.validate()
            out.append(g)
        except (KeyError, ValueError, IndexError):
            skipped += 1
    return out, skipped


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--cache", required=True)
    games, skipped = load(ap.parse_args().cache)
    rep = run_harness(games)
    rep["games_loaded"] = len(games); rep["games_skipped_invalid"] = skipped
    print(json.dumps(rep, indent=2))
