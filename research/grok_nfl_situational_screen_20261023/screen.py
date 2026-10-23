"""Held-out season screen vs naive earlier-season frequencies. No quotes, no holdout spend."""
import csv, json, math, random, sys
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else ".")
from nfl_situational_empirical import price_situational, BOTH_NS, NflSituationalError
TABLE = sys.argv[2] if len(sys.argv) > 2 else "situational_table.csv"
S = ("game_id", "date", "home", "away", "first_score")
rows = [{k: (v if k in S else int(v)) for k, v in r.items()} for r in csv.DictReader(open(TABLE))]
TESTS = range(2019, 2026); B = 2000; EPS = 1e-9
TESTS_N = 4 + len(BOTH_NS); ALPHA = 0.05 / TESTS_N
out = {"label": "SCREEN", "baseline": "naive frequency / pmf of strictly earlier seasons (+0.5 Laplace)",
       "metric": "mean log loss per game (lower is better); delta = model - naive",
       "alpha_bonferroni": ALPHA, "bootstrap_reps": B, "refused": {}, "families": {}}
rng = random.Random(20261023)
def naive(fam, s, n):
    pool = [r for r in rows if r["season"] < s]
    if fam == "LARGEST_LEAD":
        c = {}; [c.__setitem__(r["largest_lead"], c.get(r["largest_lead"], 0) + 1) for r in pool]
        mx = max(c) + 10; t = len(pool) + 0.5 * (mx + 1)
        return {k: (c.get(k, 0) + 0.5) / t for k in range(mx + 1)}
    if fam == "FIRST_SCORE":
        sc = [r for r in pool if r["first_score"] != "NONE"]; t = len(sc) + 1.0
        return {k: (sum(1 for r in sc if r["first_score"] == v) + 0.5) / t for k, v in (("home", "H"), ("away", "A"))}
    yes = sum(1 for r in pool if outcome(fam, r, n))
    return (yes + 0.5) / (len(pool) + 1)
def outcome(fam, g, n):
    if fam == "SAFETY": return g["safety_h"] + g["safety_a"] > 0
    if fam == "DST_TD": return g["dst_td_h"] + g["dst_td_a"] > 0
    if fam == "BOTH_TEAMS_TO_SCORE_N": return g["home_pts"] >= n and g["away_pts"] >= n
    if fam == "FIRST_SCORE": return {"H": "home", "A": "away", "NONE": "none"}[g["first_score"]]
    return g["largest_lead"]
def ll(p): return -math.log(max(p, EPS))
specs = [("SAFETY", None), ("DST_TD", None), ("FIRST_SCORE", None), ("LARGEST_LEAD", None)] + \
        [("BOTH_TEAMS_TO_SCORE_N", n) for n in BOTH_NS]
cache = {}
for fam, n in specs:
    key = fam if n is None else f"{fam}_{n}"; v = []
    for g in rows:
        s = g["season"]
        if s not in TESTS: continue
        try:
            p = price_situational(rows, family=fam, date=g["date"], season=s, home=g["home"], away=g["away"], n=n)
        except NflSituationalError as e:
            out["refused"][f"{key}:{e}"] = out["refused"].get(f"{key}:{e}", 0) + 1; continue
        nv = cache.setdefault((key, s), naive(fam, s, n)); y = outcome(fam, g, n)
        if fam in ("SAFETY", "DST_TD", "BOTH_TEAMS_TO_SCORE_N"):
            a, b = (ll(p["p_yes"]), ll(nv)) if y else (ll(1 - p["p_yes"]), ll(1 - nv))
        elif fam == "FIRST_SCORE":
            a, b = ll(p["probs"][y]), ll(nv[y])
        else:
            a, b = ll(p["pmf"].get(y, 0.0)), ll(nv.get(y, 0.5 / len(rows)))
        v.append((s, a, b))
    n_ = len(v); d = [a - b for _, a, b in v]
    boots = sorted(sum(d[rng.randrange(n_)] for _ in range(n_)) / n_ for _ in range(B))
    lo, hi = boots[int(B * ALPHA / 2)], boots[int(B * (1 - ALPHA / 2)) - 1]
    ps = {str(s): round(sum(a - b for ss, a, b in v if ss == s) / sum(1 for x in v if x[0] == s), 5) for s in TESTS}
    out["families"][key] = {"n": n_, "model_ll": round(sum(a for _, a, _ in v) / n_, 5),
        "naive_ll": round(sum(b for _, _, b in v) / n_, 5), "delta": round(sum(d) / n_, 5),
        "ci_bonferroni": [round(lo, 5), round(hi, 5)], "seasons_model_better": sum(1 for x in ps.values() if x < 0),
        "per_season_delta": ps,
        "verdict": "SCREEN_BEATS_NAIVE" if hi < 0 else "SCREEN_WORSE_THAN_NAIVE" if lo > 0 else "SCREEN_INCONCLUSIVE"}
print(json.dumps(out, indent=1, sort_keys=True))
