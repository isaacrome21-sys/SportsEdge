"""Run the F5 walk-forward on a local MLB Stats API schedule+linescore cache.

Usage: PYTHONPATH=. python scripts/run_mlb_f5_walkforward.py /path/to/cache [--start 2024-04-15]
The cache (one schedule JSON per month, hydrate=linescore) lives outside the repo.
"""
import argparse
import glob
import json
import os

from sportsedge.mlb_f5_walkforward import parse_schedule, run_walkforward

ap = argparse.ArgumentParser()
ap.add_argument("cache")
ap.add_argument("--start")
args = ap.parse_args()
payloads = [json.load(open(f)) for f in sorted(glob.glob(os.path.join(args.cache, "*.json")))]
games = parse_schedule(payloads)
res = run_walkforward(games, start_date=args.start)
res["games"] = len(games)
print(json.dumps(res, indent=2))
