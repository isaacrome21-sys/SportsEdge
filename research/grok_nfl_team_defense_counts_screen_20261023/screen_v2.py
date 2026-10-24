"""Held-out season screen vs naive earlier-season pmf. No quotes, no holdout spend."""
import csv, json, math, random, sys
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else ".")
from week_cluster_bootstrap import cluster_ci, week_key
from nfl_team_defense_counts_empirical import price_team_count, FAMILIES, MAX_COUNT, NflTeamDefenseError
TABLE = sys.argv[2] if len(sys.argv) > 2 else "team_count_table.csv"
rows = [{k: (v if k in ("game_id", "date", "team", "opp") else int(v)) for k, v in r.items()}
        for r in csv.DictReader(open(TABLE))]
TESTS = range(2019, 2026); B = 2000; ALPHA = 0.05 / 2; EPS = 1e-9
out = {"label": "SCREEN", "baseline": "naive empirical pmf of strictly earlier seasons, +0.5 Laplace on 0..MAX_COUNT",
       "metric": "mean log loss per team-game (lower is better); delta = model - naive",
       "alpha_bonferroni": ALPHA, "bootstrap_reps": B, "bootstrap": "week-clustered (season, week) paired percentile", "refused": {}, "families": {}}
rng = random.Random(20261023)
for fam, key in FAMILIES.items():
    v = []
    naive_cache = {}
    for g in rows:
        s = g["season"]
        if s not in TESTS: continue
        try:
            p = price_team_count(rows, family=fam, date=g["date"], season=s, team=g["team"], opp=g["opp"])
        except NflTeamDefenseError as e:
            out["refused"][f"{fam}:{e}"] = out["refused"].get(f"{fam}:{e}", 0) + 1; continue
        if s not in naive_cache:
            c = [0.5] * (MAX_COUNT + 1)
            for r in rows:
                if r["season"] < s: c[min(r[key], MAX_COUNT)] += 1
            t = sum(c); naive_cache[s] = [x / t for x in c]
        y = min(g[key], MAX_COUNT)
        v.append((s, -math.log(max(p["pmf"][y], EPS)), -math.log(naive_cache[s][y]), week_key(g["game_id"])))
    n = len(v); d = [x[1] - x[2] for x in v]
    lo, hi, n_clusters = cluster_ci(d, [x[3] for x in v], alpha=ALPHA, reps=B)
    ps = {str(s): round(sum(x[1] - x[2] for x in v if x[0] == s) / sum(1 for x in v if x[0] == s), 5) for s in TESTS}
    out["families"][fam] = {"n": n, "model_ll": round(sum(x[1] for x in v) / n, 5),
        "naive_ll": round(sum(x[2] for x in v) / n, 5), "delta": round(sum(d) / n, 5),
        "ci_bonferroni": [round(lo, 5), round(hi, 5)], "n_week_clusters": n_clusters, "seasons_model_better": sum(1 for x in ps.values() if x < 0),
        "per_season_delta": ps,
        "verdict": "SCREEN_BEATS_NAIVE" if hi < 0 else "SCREEN_WORSE_THAN_NAIVE" if lo > 0 else "SCREEN_INCONCLUSIVE"}
print(json.dumps(out, indent=1, sort_keys=True))
