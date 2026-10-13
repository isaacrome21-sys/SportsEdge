"""Run the pre-registered NBA player-layer evaluation on local caches (outside the repo).

Usage: PYTHONPATH=. python scripts/run_nba_player_harness.py --cache DIR_Q --players DIR_PLAYERS
"""
import argparse
import json
import pathlib

from scripts.run_nba_asof_harness import load
from sportsedge.sports.nba.player_harness import parse_player_box, run_player_harness

ap = argparse.ArgumentParser()
ap.add_argument("--cache", required=True)
ap.add_argument("--players", required=True)
ap.add_argument("--version", default="v1", choices=["v1", "v2"])
ap.add_argument("--baseline", default="naive", choices=["naive", "naive_oracle"])
a = ap.parse_args()
games, qs, _ = load(a.cache)
logs = []
for p in sorted(pathlib.Path(a.players).glob("*.json")):
    d = json.loads(p.read_text())
    q = json.loads((pathlib.Path(a.cache) / p.name).read_text())
    team_by_id = {str(t["id"]): t["abbr"] for t in q["teams"]}
    logs += parse_player_box(d, team_by_id)
rep = run_player_harness(games, qs, logs, version=a.version, baseline=a.baseline)
rep["player_logs"] = len(logs)
print(json.dumps(rep, indent=1))
