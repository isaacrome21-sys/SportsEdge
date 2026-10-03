#!/usr/bin/env python3
"""Out-of-sample backtest of the minimal NBA ratings model vs closing lines.

Data: public sportsbookreview archive (github.com/flancast90/sportsbookreview-scraper,
data/nba_archive_10Y.json): 2011-12 .. 2021-22 final scores with open/close spread,
total and closing moneylines.

Protocol (pre-registered in this file before looking at holdout results):
  * Model inputs are scores only; each prediction uses strictly earlier games.
  * Hyper-parameters are grid-searched on TUNE seasons (2012-2014 scored, 2011 warm-up)
    by score MSE only -- never by betting results.
  * HOLDOUT seasons 2015-2021 are scored once.
  * Rules tested: raw model-vs-close gap buckets (spread, total), walk-forward
    market-anchored adjustment (fit on prior seasons only), and moneyline edge buckets.
  * A rule is VALIDATED only if, on pooled holdout: n >= 200, hit/ROI beats -110
    breakeven with one-sided binomial p < 0.05 / (number of rules tested), and it
    beats breakeven in >= 5 of 7 holdout seasons. Anything else is a lean at most.

Evaluation only. Grants no betting authority unless a rule prints VALIDATED.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.nba.ratings_model import NBARatingsParams, replay  # noqa: E402

SOURCE_REPO = "https://github.com/flancast90/sportsbookreview-scraper.git"
SOURCE_PATH = "data/nba_archive_10Y.json"
TUNE = (2012, 2013, 2014)
HOLDOUT = (2015, 2016, 2017, 2018, 2019, 2020, 2021)
BREAKEVEN = 110 / 210
GAP_BUCKETS = (0.0, 2.0, 4.0, 6.0)
ADJ_BUCKETS = (0.5, 1.0, 1.5)
ML_EDGES = (0.02, 0.04, 0.06)
MARGIN_SIGMA = 12.0
ALIASES = {"Golden State": "Warriors", "NewJersey": "Nets", "Bobcats": "Hornets",
           "NewOrleans": "Pelicans", "Hornets": "Hornets"}


def load_source(path: str | None) -> list:
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    tmp = Path(tempfile.mkdtemp())
    subprocess.run(["git", "clone", "-q", "--depth", "1", SOURCE_REPO, str(tmp / "sbr")], check=True)
    return json.loads((tmp / "sbr" / SOURCE_PATH).read_text(encoding="utf-8"))


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def normalize(raw: list) -> list:
    games = []
    for r in raw:
        h, a = ALIASES.get(str(r.get("home_team")), str(r.get("home_team"))), ALIASES.get(str(r.get("away_team")), str(r.get("away_team")))
        hp, ap = _num(r.get("home_final")), _num(r.get("away_final"))
        if h in ("0", "", "None") or a in ("0", "", "None") or hp is None or ap is None or hp + ap < 120:
            continue
        g = {"season": int(r["season"]), "date": int(_num(r["date"])), "home": h, "away": a,
             "home_pts": hp, "away_pts": ap}
        cs, ct = _num(r.get("home_close_spread")), _num(r.get("close_over_under"))
        os_, ot = _num(r.get("home_open_spread")), _num(r.get("open_over_under"))
        g["close_spread"] = cs if cs is not None and abs(cs) <= 25 else None
        g["close_total"] = ct if ct is not None and 170 <= ct <= 270 else None
        g["open_spread"] = os_ if os_ is not None and abs(os_) <= 25 else None
        g["open_total"] = ot if ot is not None and 170 <= ot <= 270 else None
        hml, aml = _num(r.get("home_close_ml")), _num(r.get("away_close_ml"))
        ok_ml = hml is not None and aml is not None and abs(hml) >= 100 and abs(aml) >= 100
        g["home_ml"], g["away_ml"] = (hml, aml) if ok_ml else (None, None)
        games.append(g)
    return games


def predictions(games: list, params: NBARatingsParams) -> list:
    out = []

    def pre(g, r):
        m, t = r.margin_total(g["home"], g["away"])
        enough = min(r.games.get(g["home"], 0), r.games.get(g["away"], 0)) >= 5
        out.append({**g, "pm": m, "pt": t, "enough": enough})

    replay(games, params, on_pre=pre)
    return out


def tune(games: list) -> tuple[NBARatingsParams, float]:
    best = None
    for k, carry, kl in itertools.product((0.02, 0.03, 0.04, 0.05, 0.06, 0.08), (0.3, 0.5, 0.7, 0.85), (0.005, 0.01, 0.02)):
        p = NBARatingsParams(k=k, carry=carry, k_league=kl)
        rows = [r for r in predictions([g for g in games if g["season"] <= max(TUNE)], p) if r["season"] in TUNE]
        mse = sum((r["home_pts"] - r["away_pts"] - r["pm"]) ** 2 + (r["home_pts"] + r["away_pts"] - r["pt"]) ** 2 for r in rows) / len(rows)
        if best is None or mse < best[1]:
            best = (p, mse)
    return best


def american_dec(a: float) -> float:
    return 1 + (a / 100 if a > 0 else 100 / -a)


def norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def binom_p_one_sided(wins: int, n: int, p0: float) -> float:
    """P(X >= wins) for X ~ Bin(n, p0) via normal approximation w/ continuity."""
    if n == 0:
        return 1.0
    mu, sd = n * p0, math.sqrt(n * p0 * (1 - p0))
    return 1 - norm_cdf((wins - 0.5 - mu) / sd)


def ats(rows, pick):
    """pick(row) -> +1 (home/over), -1 (away/under), 0 skip; returns per-row results."""
    res = []
    for r in rows:
        s = pick(r)
        if s:
            res.append((r["season"], s))
    return res


def grade_spread(r, side, line):
    cover = r["home_pts"] - r["away_pts"] + line  # >0 home covers
    return 0 if cover == 0 else (1 if (cover > 0) == (side > 0) else -1)


def grade_total(r, side, line):
    d = r["home_pts"] + r["away_pts"] - line
    return 0 if d == 0 else (1 if (d > 0) == (side > 0) else -1)


def summarize(name, graded):
    """graded: list of (season, +1/-1/0)."""
    w = sum(1 for _, g in graded if g > 0)
    l = sum(1 for _, g in graded if g < 0)
    n = w + l
    by = {}
    for s, g in graded:
        if g:
            a = by.setdefault(s, [0, 0])
            a[0 if g > 0 else 1] += 1
    seasons_above = sum(1 for s in HOLDOUT if s in by and by[s][0] / max(1, sum(by[s])) > BREAKEVEN)
    return {"rule": name, "w": w, "l": l, "n": n, "hit": (w / n if n else None),
            "p": binom_p_one_sided(w, n, BREAKEVEN), "seasons_above": seasons_above,
            "by_season": {s: by.get(s) for s in HOLDOUT}}


def fit_wls(xs, ys):
    n = len(xs)
    if n < 50:
        return 0.0, 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    vx = sum((x - mx) ** 2 for x in xs)
    w = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / vx if vx else 0.0
    return my - w * mx, w


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", help="local nba_archive_10Y.json (default: git clone public repo)")
    ap.add_argument("--out", default="artifacts/nba/ratings_backtest_summary.json")
    args = ap.parse_args()

    games = normalize(load_source(args.source))
    params, tune_mse = tune(games)
    rows = [r for r in predictions(games, params) if r["enough"]]
    hold = [r for r in rows if r["season"] in HOLDOUT]
    sp = [r for r in hold if r["close_spread"] is not None]
    tt = [r for r in hold if r["close_total"] is not None]

    lines = ["NBA_RATINGS_BACKTEST_SUMMARY",
             f"source {SOURCE_REPO} {SOURCE_PATH}; games {len(games)}",
             f"tuned on {TUNE} by score MSE: k={params.k} carry={params.carry} k_league={params.k_league} (mse {tune_mse:.1f})",
             f"holdout {HOLDOUT[0]}-{HOLDOUT[-1]}: spread games {len(sp)}, total games {len(tt)}"]
    mae = lambda xs: sum(abs(x) for x in xs) / len(xs)
    lines.append(f"margin MAE model {mae([r['home_pts']-r['away_pts']-r['pm'] for r in sp]):.2f} | close {mae([r['home_pts']-r['away_pts']+r['close_spread'] for r in sp]):.2f}")
    lines.append(f"total  MAE model {mae([r['home_pts']+r['away_pts']-r['pt'] for r in tt]):.2f} | close {mae([r['home_pts']+r['away_pts']-r['close_total'] for r in tt]):.2f}")

    results = []
    # 1) raw gap vs close (and vs open, graded at open)
    for b in GAP_BUCKETS:
        def ps(r, b=b):
            gap = r["pm"] + r["close_spread"]  # model margin minus market margin
            return (1 if gap > 0 else -1) if abs(gap) >= b and gap != 0 else 0
        results.append(summarize(f"spread_gap_close>={b}", [(r["season"], grade_spread(r, ps(r), r["close_spread"])) for r in sp if ps(r)]))
        def pt(r, b=b):
            gap = r["pt"] - r["close_total"]
            return (1 if gap > 0 else -1) if abs(gap) >= b and gap != 0 else 0
        results.append(summarize(f"total_gap_close>={b}", [(r["season"], grade_total(r, pt(r), r["close_total"])) for r in tt if pt(r)]))
    for b in GAP_BUCKETS:
        so = [r for r in hold if r["open_spread"] is not None]
        def pso(r, b=b):
            gap = r["pm"] + r["open_spread"]
            return (1 if gap > 0 else -1) if abs(gap) >= b and gap != 0 else 0
        results.append(summarize(f"spread_gap_open>={b}", [(r["season"], grade_spread(r, pso(r), r["open_spread"])) for r in so if pso(r)]))
        to = [r for r in hold if r["open_total"] is not None]
        def pto(r, b=b):
            gap = r["pt"] - r["open_total"]
            return (1 if gap > 0 else -1) if abs(gap) >= b and gap != 0 else 0
        results.append(summarize(f"total_gap_open>={b}", [(r["season"], grade_total(r, pto(r), r["open_total"])) for r in to if pto(r)]))

    # 2) walk-forward market-anchored: residual_vs_close ~ b + w*(model - close), fit on prior seasons only
    allsp = [r for r in rows if r["close_spread"] is not None]
    alltt = [r for r in rows if r["close_total"] is not None]
    coefs = {"spread": {}, "total": {}}
    adj_sp, adj_tt = [], []
    for s in HOLDOUT:
        tr = [r for r in allsp if r["season"] < s]
        b0, w = fit_wls([r["pm"] + r["close_spread"] for r in tr], [r["home_pts"] - r["away_pts"] + r["close_spread"] for r in tr])
        coefs["spread"][s] = (round(b0, 3), round(w, 4))
        adj_sp += [(r, b0 + w * (r["pm"] + r["close_spread"])) for r in allsp if r["season"] == s]
        tr = [r for r in alltt if r["season"] < s]
        b0, w = fit_wls([r["pt"] - r["close_total"] for r in tr], [r["home_pts"] + r["away_pts"] - r["close_total"] for r in tr])
        coefs["total"][s] = (round(b0, 3), round(w, 4))
        adj_tt += [(r, b0 + w * (r["pt"] - r["close_total"])) for r in alltt if r["season"] == s]
    for t in ADJ_BUCKETS:
        results.append(summarize(f"spread_anchored_adj>={t}", [(r["season"], grade_spread(r, 1 if a > 0 else -1, r["close_spread"])) for r, a in adj_sp if abs(a) >= t]))
        results.append(summarize(f"total_anchored_adj>={t}", [(r["season"], grade_total(r, 1 if a > 0 else -1, r["close_total"])) for r, a in adj_tt if abs(a) >= t]))

    # 3) moneyline: model win prob from N(margin, sigma) vs no-vig close
    ml_rows = [r for r in hold if r["home_ml"] is not None]
    ml_out = []
    for e in ML_EDGES:
        stake = profit = 0.0
        by = {}
        for r in ml_rows:
            ph = norm_cdf(r["pm"] / MARGIN_SIGMA)
            ih, ia = 1 / american_dec(r["home_ml"]), 1 / american_dec(r["away_ml"])
            nh = ih / (ih + ia)
            for side, mp, mk, price, won in (("home", ph, nh, r["home_ml"], r["home_pts"] > r["away_pts"]),
                                             ("away", 1 - ph, 1 - nh, r["away_ml"], r["away_pts"] > r["home_pts"])):
                if mp - mk >= e:
                    pnl = (american_dec(price) - 1) if won else -1.0
                    stake += 1
                    profit += pnl
                    a = by.setdefault(r["season"], [0.0, 0])
                    a[0] += pnl
                    a[1] += 1
        roi = profit / stake if stake else None
        pos = sum(1 for s in HOLDOUT if s in by and by[s][0] > 0)
        ml_out.append({"rule": f"ml_edge>={e}", "n": int(stake), "roi": roi, "seasons_positive": pos})

    n_tests = len(results) + len(ml_out)
    alpha = 0.05 / n_tests
    validated = []
    lines.append(f"ATS/OU rules (breakeven {BREAKEVEN:.2%}; validation needs n>=200, p<{alpha:.4f}, >=5/7 seasons above):")
    for x in results:
        ok = x["n"] >= 200 and x["p"] < alpha and x["seasons_above"] >= 5
        x["validated"] = ok
        if ok:
            validated.append(x["rule"])
        hit = f"{x['hit']:.1%}" if x["hit"] is not None else "n/a"
        lines.append(f"  {x['rule']:<26} {x['w']}-{x['l']} hit {hit} p={x['p']:.3f} seasons>{x['seasons_above']}/7{'  VALIDATED' if ok else ''}")
    lines.append("Moneyline (model N(margin,12) vs no-vig close), flat 1u:")
    for x in ml_out:
        roi = f"{x['roi']:+.1%}" if x["roi"] is not None else "n/a"
        lines.append(f"  {x['rule']:<26} n {x['n']} ROI {roi} seasons+ {x['seasons_positive']}/7")
    lines.append(f"anchored coefs by held-out season: spread {coefs['spread']} | total {coefs['total']}")
    lines.append("VALIDATED MARKETS: " + (", ".join(validated) if validated else "NONE -> every NBA output is a LEAN, not a bet"))

    text = "\n".join(lines)
    print(text)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"params": params.__dict__, "tune_seasons": TUNE, "holdout_seasons": HOLDOUT,
                               "rules": results, "moneyline": ml_out, "validated": validated,
                               "anchored_coefs": coefs, "summary": text}, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
