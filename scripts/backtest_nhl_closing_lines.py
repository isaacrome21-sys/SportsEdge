#!/usr/bin/env python3
"""NHL rate-v1 spec vs CLOSING lines, out of sample, point-in-time features.

Data (public, anonymous GitHub):
  odds+scores : flancast90/sportsbookreview-scraper data/nhl_archive_10Y.json (MIT)
  shots       : ewnike/cost_of_cup Kaggle_stats/game_teams_stats.csv (Kaggle NHL Game Data mirror)
Join: same REG season, home, away, k-th meeting in order; final score must match
(Kaggle omits the shootout-winner goal, so a tied Kaggle score +1 to one side also matches).
Usage: backtest_nhl_closing_lines.py SBR_JSON GAME_TEAMS_STATS_CSV TEAM_INFO_CSV FREEZE_JSON OUT_JSON

Model A = frozen production coefficients (artifacts/nhl/nhl_rate_v1_freeze.json) exactly as the card.
Model B = same feature spec, Poisson GLM refit walk-forward (train all prior seasons, test next).
Features per team-game (season-to-date, strictly prior, >=10 prior games each):
  (GF/g, opp GA/g, SF/(SF+opp SA), 0, 0, rest=1, 0, 0, home)  -- identical to card _row.
Final score = regulation Poisson + one OT/SO goal to a coin-flip winner on ties (card path).
Bet rule = card rule: side with EV per $1 >= 2% at the closing price.
"""
from __future__ import annotations

import csv
import json
import math
import sys
from collections import defaultdict

import numpy as np

SBR = sys.argv[1]
GTS = sys.argv[2]
TEAMS = sys.argv[3]
FREEZE = sys.argv[4]
OUT = sys.argv[5]

FIX = {"St.Louis": "Blues", "Phoenix": "Coyotes", "Arizonas": "Coyotes", "Tampa": "Lightning",
       "Tampa Bay": "Lightning", "NY Islanders": "Islanders", "WinnipegJets": "Jets",
       "SeattleKraken": "Kraken"}
FLOOR = 0.02
MIN_PRIOR = 10


def dec(o: float) -> float:
    return 1 + o / 100 if o > 0 else 1 + 100 / abs(o)


def load():
    team = {r["team_id"]: r["teamName"] for r in csv.DictReader(open(TEAMS))}
    seen = set()
    per = defaultdict(dict)
    for r in csv.DictReader(open(GTS)):
        gid = r["game_id"]
        if gid[4:6] != "02" or (gid, r["HoA"]) in seen:
            continue
        seen.add((gid, r["HoA"]))
        per[gid][r["HoA"]] = (team[r["team_id"]], int(r["goals"]), int(r["shots"]))
    games = []
    for gid, d in per.items():
        if "home" in d and "away" in d:
            games.append({"gid": gid, "season": int(gid[:4]), "num": int(gid[6:]),
                          "home": d["home"][0], "away": d["away"][0],
                          "hg": d["home"][1], "ag": d["away"][1], "hs": d["home"][2], "as": d["away"][2]})
    games.sort(key=lambda g: (g["season"], g["num"]))
    sbr = json.load(open(SBR))
    by = defaultdict(list)
    for r in sbr:
        h, a = FIX.get(str(r["home_team"]), str(r["home_team"])), FIX.get(str(r["away_team"]), str(r["away_team"]))
        by[(int(r["season"]), h, a)].append(r)
    for v in by.values():
        v.sort(key=lambda r: r["date"])
    kg = defaultdict(list)
    for g in games:
        kg[(g["season"], g["home"], g["away"])].append(g)
    matched = mism = 0
    for key, gl in kg.items():
        for g, r in zip(gl, by.get(key, [])):
            try:
                sh, sa = int(r["home_final"]), int(r["away_final"])
            except ValueError:
                sh = sa = -99
            exact = (sh, sa) == (g["hg"], g["ag"])
            # Kaggle omits the shootout-winner goal; books count it.
            so = g["hg"] == g["ag"] and ((sh, sa) == (g["hg"] + 1, g["ag"]) or (sh, sa) == (g["hg"], g["ag"] + 1))
            if exact or so:
                g["odds"] = r
                g["fh"], g["fa"] = sh, sa
                matched += 1
            else:
                mism += 1
    return games, matched, mism


def add_features(games):
    acc = defaultdict(lambda: [0, 0.0, 0.0, 0.0, 0.0])  # n, gf, ga, sf, sa
    season = None
    for g in games:
        if g["season"] != season:
            acc.clear()
            season = g["season"]
        H, A = acc[g["home"]], acc[g["away"]]
        if H[0] >= MIN_PRIOR and A[0] >= MIN_PRIOR:
            hgf, hga, hsf, hsa = (x / H[0] for x in H[1:])
            agf, aga, asf, asa = (x / A[0] for x in A[1:])
            g["xh"] = (hgf, aga, hsf / (hsf + asa), 0, 0, 1.0, 0, 0, 1.0)
            g["xa"] = (agf, hga, asf / (asf + hsa), 0, 0, 1.0, 0, 0, 0.0)
        for t, gf, ga, sf, sa in ((g["home"], g["hg"], g["ag"], g["hs"], g["as"]),
                                  (g["away"], g["ag"], g["hg"], g["as"], g["hs"])):
            s = acc[t]
            s[0] += 1; s[1] += gf; s[2] += ga; s[3] += sf; s[4] += sa


def fit_poisson(X, y, ridge=1.0, iters=50):
    Xd = np.column_stack([np.ones(len(X)), X])
    b = np.zeros(Xd.shape[1]); b[0] = math.log(max(1e-6, y.mean()))
    P = ridge * np.eye(Xd.shape[1]); P[0, 0] = 0
    for _ in range(iters):
        mu = np.exp(Xd @ b)
        grad = Xd.T @ (y - mu) - P @ b
        hess = (Xd * mu[:, None]).T @ Xd + P
        step = np.linalg.solve(hess, grad)
        b += step
        if np.abs(step).max() < 1e-9:
            break
    return b


def pmf(lam, k=20):
    out = [math.exp(-lam)]
    for i in range(1, k + 1):
        out.append(out[-1] * lam / i)
    return out


def final_dist(lh, la):
    ph, pa = pmf(lh), pmf(la)
    d = defaultdict(float)
    for i, pi in enumerate(ph):
        for j, pj in enumerate(pa):
            p = pi * pj
            if i == j:
                d[(i + 1, j)] += p / 2; d[(i, j + 1)] += p / 2
            else:
                d[(i, j)] += p
    z = sum(d.values())
    return {k: v / z for k, v in d.items()}


def side_probs(dist, f):
    w = pu = l = 0.0
    for (h, a), p in dist.items():
        v = f(h, a)
        if v > 0: w += p
        elif v < 0: l += p
        else: pu += p
    return w, pu, l


class Book:
    def __init__(self):
        self.rows = []  # (won 1/0, profit, novig_p_of_side, model_p_graded)

    def add(self, won, profit, nv, mp):
        self.rows.append((won, profit, nv, mp))

    def summary(self):
        n = len(self.rows)
        if not n:
            return {"n": 0}
        w = np.array([r[0] for r in self.rows], float)
        pr = np.array([r[1] for r in self.rows], float)
        nv = np.array([r[2] for r in self.rows], float)
        se = pr.std(ddof=1) / math.sqrt(n) if n > 1 else float("nan")
        return {"n": n, "hit": round(w.mean(), 4), "avg_novig_p": round(nv.mean(), 4),
                "hit_minus_novig_pp": round(100 * (w.mean() - nv.mean()), 2),
                "roi": round(pr.mean(), 4), "roi_95ci": [round(pr.mean() - 1.96 * se, 4), round(pr.mean() + 1.96 * se, 4)]}


def evaluate(games, coef_for_season, label):
    books = defaultdict(Book)
    brier = defaultdict(lambda: [0, 0.0, 0.0])
    for g in games:
        r = g.get("odds")
        if r is None or "xh" not in g:
            continue
        b = coef_for_season(g["season"])
        if b is None:
            continue
        lh = math.exp(b[0] + float(np.dot(b[1:], g["xh"])))
        la = math.exp(b[0] + float(np.dot(b[1:], g["xa"])))
        dist = final_dist(lh, la)
        hg, ag = g["fh"], g["fa"]  # settle on book final (incl. SO goal)
        # Moneyline
        hml, aml = r["home_close_ml"], r["away_close_ml"]
        if hml and aml:
            ph = sum(p for (h, a), p in dist.items() if h > a)
            ih, ia = 1 / dec(hml), 1 / dec(aml)
            nvh = ih / (ih + ia)
            bb = brier["ML"]; bb[0] += 1; bb[1] += (ph - (hg > ag)) ** 2; bb[2] += (nvh - (hg > ag)) ** 2
            for p, o, nv, won in ((ph, hml, nvh, hg > ag), (1 - ph, aml, 1 - nvh, ag > hg)):
                if p * dec(o) - 1 >= FLOOR:
                    books["ML"].add(int(won), dec(o) - 1 if won else -1.0, nv, p)
        # Puck line (home spread from SBR)
        hs, ho, ao = r["home_close_spread"], r["home_close_spread_odds"], r["away_close_spread_odds"]
        if hs and ho and ao:
            w, pu, l = side_probs(dist, lambda h, a: h - a + hs)
            ih, ia = 1 / dec(ho), 1 / dec(ao)
            nvh = ih / (ih + ia)
            m = hg - ag + hs
            if m != 0:
                bb = brier["PL"]; bb[0] += 1; bb[1] += (w / (w + l) - (m > 0)) ** 2; bb[2] += (nvh - (m > 0)) ** 2
            for p, push, o, nv, res in ((w, pu, ho, nvh, m), (l, pu, ao, 1 - nvh, -m)):
                if p * dec(o) + push - 1 >= FLOOR and res != 0:
                    books["PL"].add(int(res > 0), dec(o) - 1 if res > 0 else -1.0, nv, p / (1 - push))
        # Total (SBR lists one total price; assume -110 both sides)
        t = r["close_over_under"]
        if t:
            o, pu, u = side_probs(dist, lambda h, a: h + a - t)
            tot = hg + ag
            if tot != t:
                bb = brier["TOTAL"]; bb[0] += 1; bb[1] += (o / (o + u) - (tot > t)) ** 2; bb[2] += (0.5 - (tot > t)) ** 2
            for p, res in ((o, tot - t), (u, t - tot)):
                if p * dec(-110) + pu - 1 >= FLOOR and res != 0:
                    books["TOTAL"].add(int(res > 0), dec(-110) - 1 if res > 0 else -1.0, 0.5, p / (1 - pu))
    out = {"model": label}
    for k in ("ML", "PL", "TOTAL"):
        s = books[k].summary()
        n, bm, bk = brier[k]
        if n:
            s["brier_model"] = round(bm / n, 5); s["brier_market_novig"] = round(bk / n, 5); s["brier_n"] = n
        out[k] = s
    return out


def main():
    games, matched, mism = load()
    add_features(games)
    frozen = json.load(open(FREEZE))["parameters"]
    bA = np.array([frozen["intercept"], frozen["offense_xg"], frozen["opponent_xga"], frozen["shot_share"],
                   frozen["special_teams"], frozen["goalie_gsax"], frozen["rest"], frozen["travel"],
                   frozen["lineup"], frozen["home_ice"]])
    test_seasons = [s for s in range(2013, 2020)]
    rowsX, rowsY = defaultdict(list), defaultdict(list)
    for g in games:
        if "xh" in g:
            rowsX[g["season"]] += [g["xh"], g["xa"]]
            rowsY[g["season"]] += [g.get("fh", g["hg"]), g.get("fa", g["ag"])]
    fits = {}
    for s in test_seasons:
        X = np.array([x for ss in rowsX if ss < s for x in rowsX[ss]], float)
        y = np.array([v for ss in rowsY if ss < s for v in rowsY[ss]], float)
        keep = [0, 1, 2, 8]  # free slots: gf, oga, shot_share, home (others are 0 / constant)
        bk = fit_poisson(X[:, keep], y)
        b = np.zeros(10); b[0] = bk[0]
        for i, k in enumerate(keep):
            b[1 + k] = bk[1 + i]
        fits[s] = b
    in_test = [g for g in games if g["season"] in test_seasons]
    res = {
        "matched_games": matched, "score_mismatch_dropped": mism, "test_seasons": "2013-14..2019-20 REG",
        "A_frozen_card": evaluate(in_test, lambda s: bA, "A frozen card coefficients"),
        "B_walkforward_refit": evaluate(in_test, lambda s: fits.get(s), "B walk-forward refit, same spec"),
        "B_coefficients_last": [round(x, 4) for x in fits[test_seasons[-1]]],
        "notes": [
            "Bet rule: EV>=2% at closing price; totals priced at -110 both sides (source has one total price).",
            "Pass (per market): OOS hit rate > breakeven (52.4% at -110 / > avg no-vig p), ROI > 0, "
            "Brier better than the no-vig market, and the frozen card coefficients (model A) must pass, not only a refit.",
        ],
    }
    json.dump(res, open(OUT, "w"), indent=2)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
