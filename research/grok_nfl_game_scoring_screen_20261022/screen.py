"""SCREEN for NFL game-scoring research engines.  Out-of-sample by
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
         "date": r["date"], "home": r["home"], "away": r["away"]}
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
fam = {f: {"model": [], "base": [], "season": []} for f in
       ["TEAM_TOTAL_TOUCHDOWNS", "TOTAL_TOUCHDOWNS", "TEAM_TD_OU_1.5", "TEAM_TD_OU_2.5",
        "TOTAL_TD_OU_4.5", "TOTAL_TD_OU_5.5", "WINNING_MARGIN"] + [f"RACE_TO_{n}" for n in E.RACE_NS]}
refused = Counter()
def add(f, m, b, s):
    fam[f]["model"].append(m); fam[f]["base"].append(b); fam[f]["season"].append(s)

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

rng = random.Random(20261022)
report = {"label": "SCREEN", "baseline": "naive empirical distribution of strictly earlier seasons",
          "metric": "mean log loss per game (lower is better); delta = model - baseline",
          "refused": dict(refused), "families": {}}
for f, d in fam.items():
    dm = [a - b for a, b in zip(d["model"], d["base"])]
    n = len(dm); mean = sum(dm) / n
    boots = sorted(sum(dm[rng.randrange(n)] for _ in range(n)) / n for _ in range(1000))
    per = {}
    for s in sorted(set(d["season"])):
        x = [v for v, ss in zip(dm, d["season"]) if ss == s]
        per[s] = round(sum(x) / len(x), 5)
    verdict = "SCREEN_BEATS_NAIVE" if boots[974] < 0 else ("SCREEN_WORSE_THAN_NAIVE" if boots[25] > 0 else "SCREEN_INCONCLUSIVE")
    report["families"][f] = {"n": n, "model_ll": round(sum(d["model"]) / n, 5), "base_ll": round(sum(d["base"]) / n, 5),
                             "delta": round(mean, 5), "ci95": [round(boots[25], 5), round(boots[974], 5)],
                             "seasons_model_better": sum(v < 0 for v in per.values()), "per_season_delta": per,
                             "verdict": verdict}
print(json.dumps(report, indent=1))
