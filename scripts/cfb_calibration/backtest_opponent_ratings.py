#!/usr/bin/env python3
"""t273: strict out-of-sample backtest of opponent-adjusted CFB ratings.

Run in the directory holding cfb_line_odds.csv.gz (pinned archive, see
build_eval_rows.py), espn_results_2023_2025.json and (optional)
espn_box_2023_2025.json. Hyperparameters and stacking weights are fit on
2024 ONLY (results only, never prices); everything is scored on 2025.
Closing/opening lines are used ONLY to score, never as model inputs.
Ratings for a game use only games whose kickoff is strictly before that
game's calendar day (UTC), plus the prior season's final ratings.
Output: SCREEN / NOT_VALIDATED.
"""
import csv, gzip, json, math, os, sys, statistics as S, collections
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import numpy as np
from sportsedge.sports.cfb.opponent_ratings import FBS_CONFERENCE_IDS, fit_ratings, predict, _when


def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def wilson(k, n, z=1.96):
    if n == 0:
        return (None, None)
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 3), round(c + h, 3))


def imp(o):
    return 100 / (o + 100) if o > 0 else -o / (-o + 100)


def load():
    R = json.load(open("espn_results_2023_2025.json"))
    box = json.load(open("espn_box_2023_2025.json")) if os.path.exists("espn_box_2023_2025.json") else {}
    games = []
    for gid, x in R.items():
        b = box.get(gid) or {}
        h, a = b.get(str(x["home"])) or {}, b.get(str(x["away"])) or {}
        games.append(dict(x, gid=gid, home=str(x["home"]), away=str(x["away"]),
                          h_box=h, a_box=a,
                          fbs_both=(x.get("home_conf") in FBS_CONFERENCE_IDS
                                    and x.get("away_conf") in FBS_CONFERENCE_IDS)))
    L = collections.defaultdict(lambda: {"sp": [], "spo": [], "spp": [], "tot": [], "toto": [], "ml": collections.defaultdict(dict)})
    for r in csv.DictReader(gzip.open("cfb_line_odds.csv.gz", "rt")):
        if r["season"] not in ("2024.0", "2025.0") or not r["game_id"] or r["game_id"] not in R:
            continue
        away, _, home = r["game_desc"].partition("@"); l = L[r["game_id"]]
        if r["market_type"] == "spread" and r["abbr"] == home and r["lines"]:
            l["sp"].append(float(r["lines"]))
            if r["opening_lines"]:
                l["spo"].append(float(r["opening_lines"]))
        elif r["market_type"] == "total" and r["abbr"] == "over" and r["lines"]:
            l["tot"].append(float(r["lines"]))
            if r["opening_lines"]:
                l["toto"].append(float(r["opening_lines"]))
        elif r["market_type"] == "money_line" and r["odds"]:
            side = "H" if r["abbr"] == home else ("A" if r["abbr"] == away else None)
            if side:
                l["ml"][r["book"]][side] = float(r["odds"])
    lines = {}
    for gid, l in L.items():
        if not l["sp"] or not l["tot"]:
            continue
        nv = [imp(v["H"]) / (imp(v["H"]) + imp(v["A"])) for v in l["ml"].values() if "H" in v and "A" in v]
        lines[gid] = {"spread": S.median(l["sp"]), "total": S.median(l["tot"]),
                      "spread_open": S.median(l["spo"]) if l["spo"] else None,
                      "total_open": S.median(l["toto"]) if l["toto"] else None,
                      "ml_nv": S.median(nv) if nv else None}
    return games, lines


def stat_games(games, key):
    """Re-express games with a per-team box stat in the hs/as slots."""
    out = []
    for g in games:
        h, a = g["h_box"].get(key), g["a_box"].get(key)
        if h is None or a is None:
            continue
        out.append(dict(g, hs=h, **{"as": a}))
    return out


def day(g):
    d = _when(g["date"])
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def season_preds(games, season, lam, rho, key=None, mu_prior=27.0, hfa_prior=3.0):
    src = games if key is None else stat_games(games, key)
    prev = [g for g in src if g["season"] == season - 1]
    prior = fit_ratings(prev, as_of=datetime(season, 3, 1, tzinfo=timezone.utc), lam=lam,
                        mu_prior=mu_prior, hfa_prior=hfa_prior) if prev else None
    cur = [g for g in src if g["season"] == season]
    targets = [g for g in games if g["season"] == season]
    by_day = collections.defaultdict(list)
    for g in targets:
        by_day[day(g)].append(g)
    out = {}
    for d in sorted(by_day):
        r = fit_ratings(cur, as_of=d, lam=lam, prior=prior, rho=rho,
                        mu_prior=prior["mu"] if prior else mu_prior,
                        hfa_prior=hfa_prior)
        for g in by_day[d]:
            out[g["gid"]] = predict(r, g["home"], g["away"], neutral=bool(g.get("neutral")),
                                    fbs_both=g["fbs_both"])
        last = r
    out["_hfa"] = (last["hfa"], last["hfa_non_fbs"]) if by_day else None
    return out


def rest_days(games):
    last = {}
    out = {}
    for g in sorted(games, key=lambda x: _when(x["date"])):
        t = _when(g["date"])
        rs = []
        for team in (g["home"], g["away"]):
            p = last.get(team)
            rs.append(min(21.0, (t - p).days) if p and p.year == t.year else 14.0)
            last[team] = t
        out[g["gid"]] = rs
    return out


def design(games, season, preds, rest, variant):
    rows = []
    for g in games:
        if g["season"] != season or g["gid"] not in preds["pts"]:
            continue
        hp, ap = preds["pts"][g["gid"]]
        f_m = [hp - ap]; f_t = [hp + ap]
        if "eff" in variant and g["gid"] in preds.get("yards", {}) and g["gid"] in preds.get("plays", {}):
            hy, ay = preds["yards"][g["gid"]]; hpl, apl = preds["plays"][g["gid"]]
            f_m.append(hy / max(hpl, 1) - ay / max(apl, 1))
            f_t.append(hy / max(hpl, 1) + ay / max(apl, 1))
        elif "eff" in variant:
            continue
        if "pace" in variant:
            if g["gid"] not in preds.get("plays", {}):
                continue
            f_t.append(sum(preds["plays"][g["gid"]]))
        if "to" in variant:
            if g["gid"] not in preds.get("to", {}):
                continue
            ht, at = preds["to"][g["gid"]]; f_m.append(at - ht)
        if "rest" in variant:
            rh, ra = rest[g["gid"]]; f_m.append(rh - ra)
        rows.append((g, f_m, f_t))
    return rows


def fit_stack(rows):
    Xm = np.array([[1.0] + f for _, f, _ in rows]); ym = np.array([g["hs"] - g["as"] for g, _, _ in rows])
    Xt = np.array([[1.0] + f for _, _, f in rows]); yt = np.array([g["hs"] + g["as"] for g, _, _ in rows])
    wm = np.linalg.lstsq(Xm, ym, rcond=None)[0]; wt = np.linalg.lstsq(Xt, yt, rcond=None)[0]
    sdm = float(np.std(ym - Xm @ wm, ddof=Xm.shape[1])); sdt = float(np.std(yt - Xt @ wt, ddof=Xt.shape[1]))
    return wm, wt, sdm, sdt


def fit_beta(rows, lines, wm, wt, sdm, sdt):
    """1-D slope on the standardized gap, fit on 2024 outcomes (grid MLE).
    beta<1 shrinks the model toward the line; beta=0 is the line itself."""
    data = {"s": [], "t": []}
    for g, fm, ft in rows:
        ln = lines.get(g["gid"])
        if not ln:
            continue
        M = float(np.dot([1.0] + fm, wm)); T = float(np.dot([1.0] + ft, wt))
        cov = (g["hs"] - g["as"]) + ln["spread"]; ov = (g["hs"] + g["as"]) - ln["total"]
        if cov != 0:
            data["s"].append(((M + ln["spread"]) / sdm, cov > 0))
        if ov != 0:
            data["t"].append(((T - ln["total"]) / sdt, ov > 0))
    out = {}
    for k, d in data.items():
        best = None
        for b in [i / 100 for i in range(0, 101)]:
            ll = sum(math.log(max(1e-9, phi(b * z) if y else 1 - phi(b * z))) for z, y in d)
            if best is None or ll > best[0]:
                best = (ll, b)
        out[k] = best[1]
    return out


def score(rows, lines, wm, wt, sdm, sdt, beta=None):
    beta = beta or {"s": 1.0, "t": 1.0}
    m = collections.Counter(); cal = collections.defaultdict(lambda: [0, 0, 0.0])
    hits = {th: {"ats": [0, 0], "ou": [0, 0]} for th in (0.0, 2.5, 3.0, 5.0)}
    clv = {"spread": [0, 0], "total": [0, 0]}
    for g, fm, ft in rows:
        ln = lines.get(g["gid"])
        if not ln:
            continue
        M = float(np.dot([1.0] + fm, wm)); T = float(np.dot([1.0] + ft, wt))
        margin, pts = g["hs"] - g["as"], g["hs"] + g["as"]
        cm = -ln["spread"]; cov = margin - cm; ov = pts - ln["total"]
        if cov != 0:
            p = phi(beta["s"] * (M - cm) / sdm); y = cov > 0
            m["n_s"] += 1; m["b_s"] += (p - y) ** 2; m["b_s_mkt"] += 0.25
            b = min(9, int(p * 10)); cal[b][0] += 1; cal[b][1] += y; cal[b][2] += p
            m["dog"] += ((M > cm) == (ln["spread"] > 0))
            for th in hits:
                if abs(M - cm) >= th and ln["spread"] != 0 or (th == 0 and abs(M - cm) > 0):
                    hits[th]["ats"][1] += 1; hits[th]["ats"][0] += ((M > cm) == y)
        if ov != 0:
            p = phi(beta["t"] * (T - ln["total"]) / sdt); y = ov > 0
            m["n_t"] += 1; m["b_t"] += (p - y) ** 2; m["b_t_mkt"] += 0.25; m["over"] += p > 0.5
            for th in hits:
                if abs(T - ln["total"]) >= th:
                    hits[th]["ou"][1] += 1; hits[th]["ou"][0] += ((T > ln["total"]) == y)
        if ln["ml_nv"] is not None and margin != 0:
            p = phi(M / sdm); y = margin > 0
            m["n_ml"] += 1; m["b_ml"] += (p - y) ** 2; m["b_ml_mkt"] += (ln["ml_nv"] - y) ** 2
        if ln["spread_open"] is not None and ln["spread_open"] != ln["spread"]:
            mv_home = ln["spread"] < ln["spread_open"]  # line moved toward home
            clv["spread"][1] += 1; clv["spread"][0] += ((M > -ln["spread_open"]) == mv_home)
        if ln["total_open"] is not None and ln["total_open"] != ln["total"]:
            clv["total"][1] += 1; clv["total"][0] += ((T > ln["total_open"]) == (ln["total"] > ln["total_open"]))
    out = {"n_spread": m["n_s"], "brier_spread": round(m["b_s"] / m["n_s"], 4),
           "brier_spread_market": round(m["b_s_mkt"] / m["n_s"], 4),
           "n_total": m["n_t"], "brier_total": round(m["b_t"] / m["n_t"], 4),
           "brier_total_market": round(m["b_t_mkt"] / m["n_t"], 4),
           "n_ml": m["n_ml"], "brier_ml": round(m["b_ml"] / max(1, m["n_ml"]), 4),
           "brier_ml_market": round(m["b_ml_mkt"] / max(1, m["n_ml"]), 4),
           "dog_share": round(m["dog"] / m["n_s"], 3), "over_share": round(m["over"] / m["n_t"], 3),
           "calib_spread": {f"{b/10:.1f}": {"n": v[0], "pred": round(v[2] / v[0], 3), "actual": round(v[1] / v[0], 3)}
                            for b, v in sorted(cal.items())},
           "hits": {str(th): {k: {"hit": v[0], "n": v[1], "rate": round(v[0] / v[1], 3) if v[1] else None,
                                   "wilson95": wilson(v[0], v[1])} for k, v in d.items()} for th, d in hits.items()},
           "clv_agreement": {k: {"agree": v[0], "n": v[1], "rate": round(v[0] / v[1], 3) if v[1] else None,
                                 "wilson95": wilson(v[0], v[1])} for k, v in clv.items()}}
    return out


def main():
    games, lines = load()
    rest = rest_days(games)
    # 1) ridge hyperparameters on 2024 only (margin MSE vs results)
    best = None
    for lam in (0.5, 1.0, 2.0, 4.0):
        for rho in (0.4, 0.6, 0.8, 1.0):
            pr = season_preds(games, 2024, lam, rho)
            err = [((g["hs"] - g["as"]) - (pr[g["gid"]][0] - pr[g["gid"]][1])) ** 2
                   for g in games if g["season"] == 2024 and g["gid"] in pr]
            mse = sum(err) / len(err)
            print("grid", lam, rho, round(mse, 2), flush=True)
            if best is None or mse < best[0]:
                best = (mse, lam, rho)
    _, lam, rho = best
    preds = {}
    for s in (2024, 2025):
        preds[s] = {"pts": season_preds(games, s, lam, rho)}
        if any(g["h_box"] for g in games):
            for key in ("yards", "plays", "to"):
                preds[s][key] = season_preds(games, s, lam, rho, key=key,
                                             mu_prior={"yards": 400.0, "plays": 70.0, "to": 1.5}[key],
                                             hfa_prior=0.0)
    variants = [("pts",), ("pts", "eff"), ("pts", "eff", "pace"), ("pts", "eff", "pace", "to"),
                ("pts", "eff", "pace", "to", "rest")]
    report = {"lam": lam, "rho": rho,
              "hfa_end_2024_fbs_vs_fbs": preds[2024]["pts"]["_hfa"][0],
              "hfa_end_2024_non_fbs": preds[2024]["pts"]["_hfa"][1],
              "hfa_end_2025_fbs_vs_fbs": preds[2025]["pts"]["_hfa"][0], "status_label": "SCREEN", "validation": "NOT_VALIDATED",
              "ablation": {}}
    for v in variants:
        if "eff" in v and not preds[2024].get("yards"):
            continue
        tr = design(games, 2024, preds[2024], rest, v)
        wm, wt, sdm, sdt = fit_stack(tr)
        beta = fit_beta(tr, lines, wm, wt, sdm, sdt)
        te = design(games, 2025, preds[2025], rest, v)
        report["ablation"]["+".join(v)] = {"weights_margin": [round(x, 4) for x in wm],
                                           "weights_total": [round(x, 4) for x in wt],
                                           "sd_margin": round(sdm, 3), "sd_total": round(sdt, 3),
                                           "beta_2024": beta,
                                           "oos_2025_uncalibrated": score(te, lines, wm, wt, sdm, sdt),
                                           "oos_2025": score(te, lines, wm, wt, sdm, sdt, beta)}
        o = report["ablation"]["+".join(v)]["oos_2025"]
        print("+".join(v), beta, o["brier_spread"], o["brier_spread_market"], o["brier_total"], o["brier_ml"],
              o["brier_ml_market"], flush=True)
    json.dump(report, open("t273_backtest.json", "w"), indent=1)


if __name__ == "__main__":
    main()
