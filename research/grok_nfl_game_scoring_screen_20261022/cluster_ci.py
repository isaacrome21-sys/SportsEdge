"""Week-clustered CIs for the game-scoring SCREEN (same rows/deltas as
screen.py; resamples whole (season, week) slates, B=10000, seed
20261022).  Also reports the Bonferroni alpha/12 two-sided interval.
SCREEN only; not validation.

Original screen docstring: SCREEN for NFL game-scoring research engines.  Out-of-sample by
season: every REG game of season S priced using only games dated before
it; residual/race fits use seasons < S only.  Naive baseline = empirical
distribution of the strictly earlier seasons (add-one smoothed).
Label: SCREEN.  Not validation; no market comparison (no admitted
historical DK quotes for these families)."""
import csv, json, math, random, sys
from collections import Counter
from sportsedge import nfl_game_scoring_empirical as E

path = sys.argv[1]
rows = []
for r in csv.DictReader(open(path)):
    d = {"game_id": r["game_id"], "season": int(r["season"]), "stype": r["stype"],
         "date": r["date"], "week": int(r["week"]), "home": r["home"], "away": r["away"]}
    for k in ("home_td", "away_td", "home_pts", "away_pts"):
        d[k] = int(r[k])
    for n in E.RACE_NS:
        d[f"race{n}"] = r[f"race{n}"]
    rows.append(d)
rows.sort(key=lambda r: (r["date"], r["game_id"]))

def ll(p): return -math.log(max(p, 1e-12))
def emp(vals, support):
    c = Counter(vals); n = len(vals)
    return {k: (c.get(k, 0) + 1) / (n + len(support)) for k in support}

cache = {}
for r in rows:
    try:
        hist = E._pit(rows, r["date"])
        cache[r["game_id"]] = {"td": E.expected(hist, r["home"], r["away"], r["season"], "td"),
                               "mu": E.margin_mu(hist, r["home"], r["away"], r["season"])}
    except E.NflGameScoringError:
        pass

TD_SUP = list(range(E.MAX_TD + 1))
fam = {f: {"model": [], "base": [], "season": [], "wk": []} for f in
       ["TEAM_TOTAL_TOUCHDOWNS", "TOTAL_TOUCHDOWNS", "TEAM_TD_OU_1.5", "TEAM_TD_OU_2.5",
        "TOTAL_TD_OU_4.5", "TOTAL_TD_OU_5.5", "WINNING_MARGIN"] + [f"RACE_TO_{n}" for n in E.RACE_NS]}
refused = Counter()
CUR = [None]
def add(f, m, b, s):
    fam[f]["wk"].append(CUR[0]); fam[f]["model"].append(m); fam[f]["base"].append(b); fam[f]["season"].append(s)

for S in range(2019, 2026):
    prior = [r for r in rows if r["season"] < S]
    b_team = emp([min(r["home_td"], E.MAX_TD) for r in prior] + [min(r["away_td"], E.MAX_TD) for r in prior], TD_SUP)
    b_tot = emp([min(r["home_td"] + r["away_td"], E.MAX_TD) for r in prior], TD_SUP)
    b_margin = E.margin_band_probs(0.0, [r["home_pts"] - r["away_pts"] for r in prior])
    res = [r["home_pts"] - r["away_pts"] - cache[r["game_id"]]["mu"] for r in prior if r["game_id"] in cache]
    race_fit, b_race = {}, {}
    for n in E.RACE_NS:
        tr = [(cache[r["game_id"]]["mu"], 1 if r[f"race{n}"] == "H" else 0) for r in prior
              if r["game_id"] in cache and r[f"race{n}"] in ("H", "A")]
        try:
            race_fit[n] = E.fit_race(tr)
        except E.NflGameScoringError as exc:
            race_fit[n] = None; refused[f"RACE_TO_{n}:{S}:{exc}"] += 1
        b_race[n] = emp([r[f"race{n}"] for r in prior], ["H", "A", "NEITHER"])
    for r in rows:
        if r["season"] != S or r["stype"] != "REG":
            continue
        CUR[0] = (S, r["week"])
        c = cache.get(r["game_id"])
        if c is None:
            refused["NO_PIT_HISTORY"] += 1; continue
        lh, la = c["td"]
        ph, pa, pt = E._poisson(lh), E._poisson(la), E._poisson(lh + la)
        ht, at = min(r["home_td"], E.MAX_TD), min(r["away_td"], E.MAX_TD)
        tt = min(ht + at, E.MAX_TD)
        add("TEAM_TOTAL_TOUCHDOWNS", (ll(ph[ht]) + ll(pa[at])) / 2, (ll(b_team[ht]) + ll(b_team[at])) / 2, S)
        add("TOTAL_TOUCHDOWNS", ll(pt[tt]), ll(b_tot[tt]), S)
        for line in (1.5, 2.5):
            bo = sum(v for k, v in b_team.items() if k > line)
            m = [E.p_over(ph, line), E.p_over(pa, line)]
            y = [ht > line, at > line]
            add(f"TEAM_TD_OU_{line}", sum(ll(p if yy else 1 - p) for p, yy in zip(m, y)) / 2,
                sum(ll(bo if yy else 1 - bo) for yy in y) / 2, S)
        for line in (4.5, 5.5):
            bo = sum(v for k, v in b_tot.items() if k > line)
            p = E.p_over(pt, line); y = tt > line
            add(f"TOTAL_TD_OU_{line}", ll(p if y else 1 - p), ll(bo if y else 1 - bo), S)
        m = r["home_pts"] - r["away_pts"]
        k = "TIE" if m == 0 else next(("H" if m > 0 else "A", lo, hi) for lo, hi in E.MARGIN_BANDS if lo <= abs(m) <= hi)
        add("WINNING_MARGIN", ll(E.margin_band_probs(c["mu"], res)[k]), ll(b_margin[k]), S)
        for n in E.RACE_NS:
            o = r[f"race{n}"]
            if race_fit[n] is None:
                continue
            pr = E.race_probs(c["mu"], race_fit[n], b_race[n]["NEITHER"])
            add(f"RACE_TO_{n}", ll(pr[o]), ll(b_race[n][o]), S)


B = 10000
K = len(fam)
rng = random.Random(20261022)
out = {"label": "SCREEN", "cluster": "(season, week)", "B": B, "seed": 20261022,
       "bonferroni_k": K, "families": {}}
for f, d in fam.items():
    dm = [a - b for a, b in zip(d["model"], d["base"])]
    cl = {}
    for v, w in zip(dm, d["wk"]):
        cl.setdefault(w, []).append(v)
    keys = sorted(cl); sums = [sum(cl[k]) for k in keys]; ns = [len(cl[k]) for k in keys]
    G = len(keys)
    boots = []
    for _ in range(B):
        idx = [rng.randrange(G) for _ in range(G)]
        boots.append(sum(sums[i] for i in idx) / sum(ns[i] for i in idx))
    boots.sort()
    q = lambda p: boots[min(B - 1, max(0, int(round(p * B)) - 1))] if p > 0.5 else boots[int(p * B)]
    lo95, hi95 = q(0.025), q(0.975)
    a = 0.05 / K
    lob, hib = q(a / 2), q(1 - a / 2)
    out["families"][f] = {"n": len(dm), "clusters": G, "delta": round(sum(dm) / len(dm), 5),
                          "ci95_week_clustered": [round(lo95, 5), round(hi95, 5)],
                          "ci_bonferroni_week_clustered": [round(lob, 5), round(hib, 5)],
                          "passes_bonferroni": hib < 0}
print(json.dumps(out, indent=1))
