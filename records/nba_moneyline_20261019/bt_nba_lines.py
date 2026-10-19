"""NBA spread / total / moneyline backtest.

Data: scratchpad/nbaodds/Data/OddsData.sqlite (2007-08..2025-26). Lines have NO prices (spread/total) and NO timestamps.
Model: SportsEdge NBA ratings_model (results-only, online, predict-before-update), imported from nba_track/wt.
Spread/total bets priced at -110 (assumed; stated in the output). Moneyline bets priced at the stored ML (two-sided, de-vigged for the market prob).
Test window: 2022-23..2025-26 (same as nba_replay.py). Train window for the ML normal-sd: 2010-11..2021-22 (not tuned on test).
"""
import json
import math
import sqlite3
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, "/tmp/claude-0/-home-claude/9ad8939a-d405-5e90-91e1-814a8660e93e/scratchpad/backtest_sweep")
from common import boot, verdict, record, implied_from_american, dec_from_american, pnl_flat  # noqa: E402

DB = "/tmp/claude-0/-home-claude/9ad8939a-d405-5e90-91e1-814a8660e93e/scratchpad/nbaodds/Data/OddsData.sqlite"
REPO = "/tmp/claude-0/-home-claude/9ad8939a-d405-5e90-91e1-814a8660e93e/scratchpad/nba_track/wt"
sys.path.insert(0, REPO)
from sportsedge.sports.nba.ratings_model import NBARatingsParams, replay  # noqa: E402

c = sqlite3.connect(DB)
tables = [r[0] for r in c.execute("select name from sqlite_master where type='table'")]
by_season, plain = {}, {}
for t in tables:
    name = t.replace("odds_", "").replace("_new", "")
    if len(name) != 7 or name[4] != "-":
        continue
    (by_season.__setitem__(name, t) if (name not in by_season or t.endswith("_new")) else None)
    if not t.endswith("_new"):
        plain[name] = t

# Table-choice audit: which table has more distinct games per season (the replay script prefers *_new)
audit = {}
for s in sorted(set(by_season) | set(plain)):
    row = {}
    for label, t in (("new", by_season.get(s)), ("plain", plain.get(s))):
        if t is None:
            continue
        row[label] = c.execute(f'select count(*), count(distinct Date||Home||Away) from "{t}"').fetchone()
    audit[s] = row

games = []
for season, t in sorted(by_season.items()):
    for d, h, a, ou, sp, mlh, mla, pts, mg in c.execute(
            f'select Date,Home,Away,OU,Spread,ML_Home,ML_Away,Points,Win_Margin from "{t}"'):
        if pts is None or mg is None or sp is None or ou is None:
            continue
        try:
            sp = 0.0 if str(sp).upper() in ("PK", "PICK") else float(sp)
            ou = float(ou)
        except ValueError:
            continue
        games.append({"date": str(d)[:10], "season": season, "home": h, "away": a, "home_pts": (pts + mg) / 2,
                      "away_pts": (pts - mg) / 2, "spread": sp, "ou": ou, "mlh": mlh, "mla": mla,
                      "margin": float(mg), "total": float(pts)})
seen, uniq = set(), []
for g in games:
    k = (g["date"], g["home"], g["away"])
    if k not in seen:
        seen.add(k)
        uniq.append(g)
games = uniq
print("games", len(games), "seasons", games[0]["season"], "-", games[-1]["season"])

# Sign check (spread > 0 = home favored): favored team should win ~0.66
nz = [g for g in games if g["spread"] != 0]
fav = np.mean([(g["spread"] > 0) == (g["margin"] > 0) for g in nz])
print(f"sign check: spread-favored side won {fav:.3f} (expect ~0.66)")

pred = {}


def on_pre(g, r):
    try:
        m, t = r.margin_total(g["home"], g["away"])
    except Exception:
        return
    pred[(g["date"], g["home"], g["away"])] = (m, t)


replay(games, NBARatingsParams(), on_pre=on_pre)
print("predictions made", len(pred))

# Clean test set: spread and moneyline agree on favorite (same filter as nba_replay.py)
def ml_fav_home(g):
    return float(g["mlh"]) < float(g["mla"])


test = []
for g in games:
    k = (g["date"], g["home"], g["away"])
    if g["season"] < "2022-23" or k not in pred:
        continue
    try:
        ok = (g["spread"] == 0) or (ml_fav_home(g) == (g["spread"] > 0))
    except (TypeError, ValueError):
        ok = False
    if ok:
        test.append((g, pred[k][0], pred[k][1]))
print("test games (2022-23..2025-26, clean):", len(test))

results = {"audit": audit, "sign_check_fav_win": round(float(fav), 4), "test_n": len(test)}

PRIMARY = 2.0
THRS = [2.0, 4.0, 6.0]


def ats_block(kind):
    out = {}
    for th in THRS:
        vals, clus_d, clus_s, push_n = [], [], [], 0
        for g, mm, tt in test:
            if kind == "spread":
                edge = mm - g["spread"]
                actual = g["margin"] - g["spread"]  # home covers if > 0
            else:
                edge = tt - g["ou"]
                actual = g["total"] - g["ou"]  # over covers if > 0
            if abs(edge) < th:
                continue
            push = actual == 0
            if push:
                push_n += 1
            # bet home (spread) / over (total) if edge > 0, else away / under
            side_home_or_over = edge > 0
            win = (actual > 0) if side_home_or_over else (actual < 0)
            vals.append(float(pnl_flat([win], [push], [1.90909090909])[0]))
            clus_d.append(g["date"])
            clus_s.append(g["season"])
        n_bets = len(vals)
        hit = (sum(1 for v in vals if v > 0) / max(1, sum(1 for v in vals if v != 0)))
        out[th] = {"n": n_bets, "pushes": push_n, "hit_non_push": round(hit, 4),
                   "roi_date": boot(vals, clus_d), "roi_season": boot(vals, clus_s)}
    return out


sp_res = ats_block("spread")
tot_res = ats_block("total")
results["spread"] = sp_res
results["total"] = tot_res
for label, res in (("spread", sp_res), ("total", tot_res)):
    for th in THRS:
        r = res[th]
        v = verdict(r["n"], r["roi_date"], r["roi_season"])
        print(f"{label} >= {th}: n={r['n']} hit={r['hit_non_push']} ROI={r['roi_date']['mean']*100:+.2f}% "
              f"date CI [{r['roi_date']['lo']*100:+.2f},{r['roi_date']['hi']*100:+.2f}] "
              f"season CI [{r['roi_season']['lo']*100:+.2f},{r['roi_season']['hi']*100:+.2f}] -> {v}")

# Model vs line accuracy (RMSE and slope), for context
def rmse(x):
    return math.sqrt(float(np.mean(np.square(x))))


e_model_sp = [mm - g["margin"] for g, mm, tt in test]
e_line_sp = [g["spread"] - g["margin"] for g, mm, tt in test]
tv = [(g, mm, tt) for g, mm, tt in test]
e_model_tot = [tt - g["total"] for g, mm, tt in tv]
e_line_tot = [g["ou"] - g["total"] for g, mm, tt in tv]
results["rmse"] = {"spread_model": rmse(e_model_sp), "spread_line": rmse(e_line_sp),
                   "total_model": rmse(e_model_tot), "total_line": rmse(e_line_tot)}
print("RMSE spread model/line", round(rmse(e_model_sp), 3), round(rmse(e_line_sp), 3),
      "total model/line", round(rmse(e_model_tot), 3), round(rmse(e_line_tot), 3))

# ---- Moneyline: model win prob from margin ~ Normal(mm, sd). sd fitted on 2010-11..2021-22 residuals only.
train_resid = []
for g in games:
    k = (g["date"], g["home"], g["away"])
    if "2010-11" <= g["season"] <= "2021-22" and k in pred:
        train_resid.append(g["margin"] - pred[k][0])
sd = float(np.std(train_resid))
print("ML normal sd (train 2010-11..2021-22):", round(sd, 2))


def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


ml_rows = []
for g, mm, tt in test:
    try:
        qh = float(implied_from_american(float(g["mlh"])))
        qa = float(implied_from_american(float(g["mla"])))
    except (TypeError, ValueError):
        continue
    if qh + qa <= 0:
        continue
    p_mkt_home = qh / (qh + qa)
    p_mod_home = phi(mm / sd)  # P(margin > 0)
    ml_rows.append((g, p_mod_home, p_mkt_home, float(dec_from_american(float(g["mlh"]))), float(dec_from_american(float(g["mla"])))))
print("ML rows", len(ml_rows), "mean overround (pair sum-1):",
      round(float(np.mean([implied_from_american(float(g["mlh"])) + implied_from_american(float(g["mla"])) - 1 for g, *_ in ml_rows])), 4))

ml_out = {}
for th in (0.02, 0.04):
    vals, cd, cs = [], [], []
    for g, pm, pk, dh, da in ml_rows:
        e = pm - pk
        if abs(e) < th:
            continue
        home = e > 0
        win = (g["margin"] > 0) if home else (g["margin"] < 0)
        dec = dh if home else da
        vals.append(float(pnl_flat([win], [False], [dec])[0]))
        cd.append(g["date"])
        cs.append(g["season"])
    hit = float(np.mean([v > 0 for v in vals])) if vals else None
    ml_out[th] = {"n": len(vals), "hit": hit, "roi_date": boot(vals, cd), "roi_season": boot(vals, cs)}
    v = verdict(len(vals), ml_out[th]["roi_date"], ml_out[th]["roi_season"])
    r = ml_out[th]
    print(f"ML edge>={th}: n={r['n']} hit={hit} ROI={r['roi_date']['mean']*100:+.2f}% "
          f"date CI [{r['roi_date']['lo']*100:+.2f},{r['roi_date']['hi']*100:+.2f}] -> {v}")
results["ml"] = ml_out
results["ml_sd"] = sd

# Brier: model vs market (no-vig), diagnostic
bm = [(pm - (1.0 if g["margin"] > 0 else 0.0)) ** 2 for g, pm, pk, *_ in ml_rows]
bk = [(pk - (1.0 if g["margin"] > 0 else 0.0)) ** 2 for g, pm, pk, *_ in ml_rows]
diff = [a - b for a, b in zip(bm, bk)]
results["ml_brier_diff_model_minus_mkt"] = boot(diff, [g["date"] for g, *_ in ml_rows])
print("ML Brier diff (model - market):", round(float(np.mean(diff)), 5), results["ml_brier_diff_model_minus_mkt"])

Path(__file__).with_name("nba_lines_results.json").write_text(json.dumps(results, indent=1, default=float))

# rows for the report
LABEL = "NBA ratings model (SportsEdge, results-only) vs OddsData line"
for label, res, kind in (("spread", sp_res, "spread"), ("total", tot_res, "total")):
    for th in THRS:
        r = res[th]
        record({"id": f"nba_{kind}_{th}", "sport": "NBA", "market": f"{kind} (model)",
                "window": "2022-23..2025-26", "primary": th == PRIMARY,
                "n": r["n"], "metric": f"flat ROI at -110 (assumed), {kind} edge >= {th} pts, hit {r['hit_non_push']}",
                "result": f"{r['roi_date']['mean']*100:+.2f}%", "ci": f"[{r['roi_date']['lo']*100:+.2f}, {r['roi_date']['hi']*100:+.2f}] date-clustered; season CI not computed (4 seasons)",
                "verdict": verdict(r["n"], r["roi_date"], r["roi_season"]),
                "note": "No prices or timestamps in source; close vs open not testable. Results-only model."})
for th in (0.02, 0.04):
    r = ml_out[th]
    record({"id": f"nba_ml_{th}", "sport": "NBA", "market": "moneyline (model vs de-vig)",
            "window": "2022-23..2025-26", "primary": th == 0.02,
            "n": r["n"], "metric": f"flat ROI at quoted ML, model p - no-vig p >= {th}, hit {round(r['hit'],3) if r['hit'] else None}",
            "result": f"{r['roi_date']['mean']*100:+.2f}%", "ci": f"[{r['roi_date']['lo']*100:+.2f}, {r['roi_date']['hi']*100:+.2f}] date-clustered",
            "verdict": verdict(r["n"], r["roi_date"], r["roi_season"]),
            "note": "Win prob = Normal(model margin, sd fitted 2010-21). Two-sided ML de-vig. Model is a distributional assumption."})
