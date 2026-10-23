"""Held-out season screen vs naive earlier-season pool. No quotes, no holdout spend."""
import csv, json, math, random, sys
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else ".")
from nfl_period_lines_empirical import price_period, PERIODS, NflPeriodLinesError, _pmf
TABLE = sys.argv[2] if len(sys.argv) > 2 else "period_table.csv"
rows = []
for r in csv.DictReader(open(TABLE)):
    d = {k: (int(v) if k not in ("game_id", "date", "home", "away") else v) for k, v in r.items()}
    rows.append(d)
TESTS = range(2019, 2026); EPS = 1e-6; B = 2000; ALPHA = 0.05 / 18
def rps(pmf, y):
    ks = range(min(min(pmf), y) - 1, max(max(pmf), y) + 1); c = s = 0.0
    for k in ks:
        c += pmf.get(k, 0.0); s += (c - (1.0 if k >= y else 0.0)) ** 2
    return s
out = {"label": "SCREEN", "baseline": "naive empirical pmf of strictly earlier seasons",
       "metrics": {"moneyline": "3-way log loss", "spread": "RPS of margin pmf", "total": "RPS of total pmf"},
       "lower_is_better": True, "alpha_bonferroni": ALPHA, "bootstrap_reps": B, "refused": {}, "families": {}}
rng = random.Random(20261023)
for per in PERIODS:
    D = {"moneyline": [], "spread": [], "total": []}; seasons = {k: {} for k in D}
    for g in rows:
        if g["season"] not in TESTS: continue
        try:
            p = price_period(rows, date=g["date"], season=g["season"], home=g["home"], away=g["away"], period=per)
        except NflPeriodLinesError as e:
            out["refused"][str(e)] = out["refused"].get(str(e), 0) + 1; continue
        pool = [r for r in rows if r["season"] < g["season"]]
        nm = _pmf([r[f"{per}_h"] - r[f"{per}_a"] for r in pool]); nt = _pmf([r[f"{per}_h"] + r[f"{per}_a"] for r in pool])
        m = g[f"{per}_h"] - g[f"{per}_a"]; t = g[f"{per}_h"] + g[f"{per}_a"]
        o = "home" if m > 0 else "away" if m < 0 else "tie"
        nml = {"home": sum(v for k, v in nm.items() if k > 0), "tie": nm.get(0, 0), "away": sum(v for k, v in nm.items() if k < 0)}
        vals = {"moneyline": (-math.log(max(p["moneyline_3way"][o], EPS)), -math.log(max(nml[o], EPS))),
                "spread": (rps(p["margin_pmf"], m), rps(nm, m)), "total": (rps(p["total_pmf"], t), rps(nt, t))}
        for k, (a, b) in vals.items():
            D[k].append((g["season"], a, b))
    for k, v in D.items():
        n = len(v); dm = sum(a - b for _, a, b in v) / n
        boots = sorted(sum((lambda x: x[1] - x[2])(v[rng.randrange(n)]) for _ in range(n)) / n for _ in range(B))
        lo = boots[int(B * ALPHA / 2)]; hi = boots[int(B * (1 - ALPHA / 2)) - 1]
        ps = {}
        for s in TESTS:
            sv = [a - b for ss, a, b in v if ss == s]; ps[str(s)] = round(sum(sv) / len(sv), 5)
        out["families"][f"{per.upper()}_{k.upper()}"] = {
            "n": n, "model": round(sum(a for _, a, _ in v) / n, 5), "naive": round(sum(b for _, _, b in v) / n, 5),
            "delta": round(dm, 5), "ci_bonferroni": [round(lo, 5), round(hi, 5)],
            "seasons_model_better": sum(1 for x in ps.values() if x < 0), "per_season_delta": ps,
            "verdict": "SCREEN_BEATS_NAIVE" if hi < 0 else "SCREEN_WORSE_THAN_NAIVE" if lo > 0 else "SCREEN_INCONCLUSIVE"}
print(json.dumps(out, indent=1, sort_keys=True))
