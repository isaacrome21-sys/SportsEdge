"""Run the CBB as-of ratings walk-forward on a local ESPN cache (outside the repo).

Usage: PYTHONPATH=. python scripts/run_cbb_asof_harness.py /workspace/cbb_cache
Cache: sb/YYYYMMDD.json (trimmed scoreboard events) and games/<id>.json (trimmed box stats).
"""
import glob
import json
import os
import sys
from datetime import datetime

from sportsedge.sports.cbb.asof_harness import run_harness
from sportsedge.sports.cbb.asof_ratings import CBBGame, possessions

cache = sys.argv[1]
games, skipped = [], 0
for f in sorted(glob.glob(os.path.join(cache, "sb", "*.json"))):
    for e in json.load(open(f)):
        try:
            t = {x["homeAway"]: x for x in e["teams"]}
            box = json.load(open(os.path.join(cache, "games", e["id"] + ".json")))
            poss = []
            for bt in box["teams"]:
                s = bt["stats"]
                fga = float(s["fieldGoalsMade-fieldGoalsAttempted"].split("-")[1])
                fta = float(s["freeThrowsMade-freeThrowsAttempted"].split("-")[1])
                poss.append(possessions(fga, float(s["offensiveRebounds"]), float(s.get("totalTurnovers") or s["turnovers"]), fta))
            games.append(CBBGame(e["id"], datetime.fromisoformat(e["date"].replace("Z", "+00:00")),
                                 t["home"]["id"], t["away"]["id"], int(t["home"]["score"]), int(t["away"]["score"]),
                                 sum(poss) / len(poss), bool(e.get("neutral")), bool(e.get("completed"))))
        except (KeyError, ValueError, TypeError, FileNotFoundError, ZeroDivisionError):
            skipped += 1
rep = run_harness(games)
rep["games_loaded"], rep["skipped"] = len(games), skipped
print(json.dumps(rep, indent=1))
