"""Independent recount of the CFB four-family population (R3) and Path B.
Reads ONLY the pinned raw sources; imports nothing from the repo."""
import csv, gzip, json, collections, sys
# usage: recount_independent.py <schedules_dir> <team_info.json> <cfb_four_family_bindings_v1.json>
SCHED, TEAMS, BINDINGS = sys.argv[1], sys.argv[2], sys.argv[3]
teams = {str(t["team_id"]): t for t in json.load(open(TEAMS))}
b = json.load(open(BINDINGS))
fcs_override = {str(t["team_id"]): set(t.get("fcs_seasons", [])) for t in b["fbs_membership_overrides"]["teams"]}
fbs_override = {str(t["team_id"]): set(t.get("fbs_seasons", [])) for t in b["fbs_membership_overrides"]["teams"]}
def is_fbs(tid, season):
    t = teams.get(tid)
    if t is None: return None
    if season in fcs_override.get(tid, ()): return False
    if season in fbs_override.get(tid, ()): return True
    return (t.get("classification") or "").lower() == "fbs"
def is_il(tid):
    t = teams.get(tid); return bool(t) and (t.get("state") or "").upper() == "IL"
rows = []
for s in range(2013, 2026):
    for r in csv.DictReader(gzip.open(f"{SCHED}/cfb_schedule_{s}.csv.gz", "rt")):
        rows.append(r)
seen, games = set(), []
for r in rows:
    if r["game_id"] in seen: continue
    if r["home_score"] in ("", "NA") or r["away_score"] in ("", "NA"): continue
    seen.add(r["game_id"]); games.append(r)
c = collections.Counter(); pop = []
for g in games:
    s = int(g["season"]); h, a = g["home_id"], g["away_id"]
    if is_il(h) or is_il(a): c["IL"] += 1; continue
    fh, fa = is_fbs(h, s), is_fbs(a, s)
    if fh is None or fa is None: c["UNRESOLVED"] += 1; continue
    if not (fh and fa): c["NON_FBS"] += 1; continue
    pop.append(g)
post = [g for g in pop if g["season_type"] != "2"]
reg = [g for g in pop if g["season_type"] == "2"]
out = {"decided_games": len(games), "excl": dict(c), "population_all": len(pop),
       "postseason_in_population": len(post), "path_B_regular_only": len(reg),
       "per_eval_fold_all": {s: sum(1 for g in pop if int(g["season"]) == s) for s in range(2021, 2026)},
       "per_eval_fold_regular": {s: sum(1 for g in reg if int(g["season"]) == s) for s in range(2021, 2026)},
       "burn_in_all": sum(1 for g in pop if int(g["season"]) <= 2020),
       "burn_in_regular": sum(1 for g in reg if int(g["season"]) <= 2020),
       "season_type_counts": dict(collections.Counter(g["season_type"] for g in pop))}
print(json.dumps(out, indent=1))
