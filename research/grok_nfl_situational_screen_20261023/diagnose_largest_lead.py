"""Diagnostic only: decompose why LARGEST_LEAD v1 loses to naive. Nothing here is adopted."""
import csv, json, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(sys.argv[1])))
from sportsedge.nfl_situational_empirical import _pmf, price_situational_unrestricted, LEAD_BETA, LEAD_REF
from sportsedge.screen_only_guard import screen_only
S = ("game_id", "date", "home", "away", "first_score")
rows = [{k: (v if k in S else int(v)) for k, v in r.items()} for r in csv.DictReader(open(sys.argv[2]))]
EPS = 1e-9
def lap(pmf, mx, n):
    t = n + 0.5 * (mx + 1); return {k: (pmf.get(k, 0) * n + 0.5) / t for k in range(mx + 1)}
acc = {k: 0.0 for k in ("model_v1", "naive_smoothed", "naive_unsmoothed", "model_smoothed", "zero_mass_loss")}
zero = n = 0; shifts = []
with screen_only():
    for g in rows:
        s = g["season"]
        if s < 2019: continue
        pool = [r["largest_lead"] for r in rows if r["season"] < s]; mx = max(pool) + 10
        raw = _pmf(pool)
        p = price_situational_unrestricted(rows, family="LARGEST_LEAD", date=g["date"], season=s, home=g["home"], away=g["away"])
        y = g["largest_lead"]; n += 1
        shifts.append(LEAD_BETA * (abs(p["mu_home"] - p["mu_away"]) - LEAD_REF))
        lv1 = -math.log(max(p["pmf"].get(y, 0.0), EPS)); acc["model_v1"] += lv1
        if p["pmf"].get(y, 0.0) < 1e-6: zero += 1; acc["zero_mass_loss"] += lv1
        acc["naive_smoothed"] += -math.log(lap(raw, mx, len(pool)).get(y, 0.5 / (len(pool) + 0.5 * (mx + 1))))
        acc["naive_unsmoothed"] += -math.log(max(raw.get(y, 0.0), EPS))
        sm = lap(p["pmf"], max(mx, max(p["pmf"])), len(pool))
        acc["model_smoothed"] += -math.log(sm.get(y, 0.5 / (len(pool) + 0.5 * (mx + 1))))
out = {k: round(v / n, 5) for k, v in acc.items()}
out.update(n=n, zero_mass_games=zero, mean_shift=round(sum(shifts) / n, 4),
           mean_abs_shift=round(sum(abs(x) for x in shifts) / n, 4),
           label="DIAGNOSTIC_ONLY_NOT_ADOPTED_NO_RETUNING")
print(json.dumps(out, indent=1, sort_keys=True))
