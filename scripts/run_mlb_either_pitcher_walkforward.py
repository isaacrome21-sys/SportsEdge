"""Run the Either-Pitcher walk-forward on a local cache (outside the repo).

Usage: PYTHONPATH=. python scripts/run_mlb_either_pitcher_walkforward.py /workspace/mlb_cache_pp
Cache: YYYY-MM.json schedules (hydrate=probablePitcher,linescore) and logs/YYYY-<pid>.json game logs.
"""
import glob
import json
import os
import sys

from sportsedge.mlb_either_pitcher_walkforward import build_events, decide, load_logs, run_season

cache = sys.argv[1]
out = {}
for y in ("2024", "2025"):
    sched = [json.load(open(f)) for f in sorted(glob.glob(os.path.join(cache, y + "-*.json")))]
    logs = load_logs(glob.glob(os.path.join(cache, "logs", y + "-*.json")))
    out[y] = run_season(build_events(sched, logs))
out["decision_2025"] = decide(out["2025"])
print(json.dumps(out, indent=1))
