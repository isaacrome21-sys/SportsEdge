#!/usr/bin/env python3
"""NBA ratings model v2 (v1 + rest / back-to-back) -- out-of-sample backtest vs lines.

Pre-registered before any v2 holdout number was computed (2026-10-04):
  * Base = the v1 scores-only ratings model with v1's TUNE-selected params
    (scripts/backtest_nba_ratings_vs_lines.py, tuned on 2012-2014 by score MSE).
  * Rest features from the schedule only: days since each team's previous game
    (capped at 4; first game of a season = 4), b2b = rest == 1.
  * Rest adjustment = OLS on TUNE seasons (2012-2014) ONLY of the v1 residual:
        margin_resid ~ c0 + c1*(b2b_away - b2b_home) + c2*(min(rest_h,3) - min(rest_a,3))
        total_resid  ~ d0 + d1*(b2b_home + b2b_away)
    Coefficients are frozen and applied to HOLDOUT 2015-2021.
  * Rule list is fixed below (V2_RULES). Because the 2015-2021 holdout was already
    looked at once by v1 (25 tests), the Bonferroni denominator is v1 + v2 tests.
  * Gate (same as v1): n >= 200, one-sided p < 0.05 / total_tests vs -110 breakeven,
    and above breakeven in >= 5 of 7 holdout seasons. Anything else stays a lean.

Evaluation only. Grants no betting authority unless a rule prints VALIDATED.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import backtest_nba_ratings_vs_lines as v1  # noqa: E402

V1_TESTS = 25
REST_CAP = 4


def _d(yyyymmdd: int) -> dt.date:
    s = str(int(yyyymmdd))
    return dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def add_rest(rows: list) -> list:
    """Attach rest_h/rest_a/b2b_h/b2b_a using strictly earlier games (schedule only)."""
    last: dict = {}
    out = []
    for r in sorted(rows, key=lambda x: (x["date"], x["home"])):
        day = _d(r["date"])
        rest = {}
        for side, team in (("h", r["home"]), ("a", r["away"])):
            prev = last.get((r["season"], team))
            rest[side] = REST_CAP if prev is None else min(REST_CAP, (day - prev).days)
            last[(r["season"], team)] = day
        out.append({**r, "rest_h": rest["h"], "rest_a": rest["a"],
                    "b2b_h": int(rest["h"] == 1), "b2b_a": int(rest["a"] == 1)})
    return out


def margin_x(r):
    return [1.0, r["b2b_a"] - r["b2b_h"], min(r["rest_h"], 3) - min(r["rest_a"], 3)]


def total_x(r):
    return [1.0, r["b2b_h"] + r["b2b_a"]]


def ols(X: list, y: list) -> list:
    """Normal-equations OLS (tiny k, no numpy dependency)."""
    k = len(X[0])
    A = [[sum(x[i] * x[j] for x in X) for j in range(k)] for i in range(k)]
    b = [sum(x[i] * yy for x, yy in zip(X, y)) for i in range(k)]
    for i in range(k):  # Gauss-Jordan
        piv = A[i][i]
        A[i] = [v / piv for v in A[i]]
        b[i] /= piv
        for j in range(k):
            if j != i:
                f = A[j][i]
                A[j] = [vj - f * vi for vj, vi in zip(A[j], A[i])]
                b[j] -= f * b[i]
    return b


def dot(c, x):
    return sum(a * b for a, b in zip(c, x))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", help="local nba_archive_10Y.json (default: git clone public repo)")
    ap.add_argument("--out", default="artifacts/nba/ratings_v2_rest_backtest_summary.json")
    args = ap.parse_args()

    games = v1.normalize(v1.load_source(args.source))
    params, _ = v1.tune(games)
    rows = add_rest([r for r in v1.predictions(games, params) if r["enough"]])

    tune_rows = [r for r in rows if r["season"] in v1.TUNE]
    cm = ols([margin_x(r) for r in tune_rows], [r["home_pts"] - r["away_pts"] - r["pm"] for r in tune_rows])
    ct = ols([total_x(r) for r in tune_rows], [r["home_pts"] + r["away_pts"] - r["pt"] for r in tune_rows])
    for r in rows:
        r["pm2"] = r["pm"] + dot(cm, margin_x(r))
        r["pt2"] = r["pt"] + dot(ct, total_x(r))

    hold = [r for r in rows if r["season"] in v1.HOLDOUT]
    sp = [r for r in hold if r["close_spread"] is not None]
    tt = [r for r in hold if r["close_total"] is not None]
    so = [r for r in hold if r["open_spread"] is not None]
    to = [r for r in hold if r["open_total"] is not None]
    mae = lambda xs: sum(abs(x) for x in xs) / len(xs)

    def gap_rule(name, pool, gapf, grade, line_key, b):
        graded = []
        for r in pool:
            g = gapf(r)
            if g != 0 and abs(g) >= b:
                graded.append((r["season"], grade(r, 1 if g > 0 else -1, r[line_key])))
        return v1.summarize(name, graded)

    results = []
    for b in (2.0, 4.0, 6.0):
        results.append(gap_rule(f"v2_spread_gap_close>={b}", sp, lambda r: r["pm2"] + r["close_spread"], v1.grade_spread, "close_spread", b))
        results.append(gap_rule(f"v2_total_gap_close>={b}", tt, lambda r: r["pt2"] - r["close_total"], v1.grade_total, "close_total", b))
    for b in (4.0, 6.0):
        results.append(gap_rule(f"v2_spread_gap_open>={b}", so, lambda r: r["pm2"] + r["open_spread"], v1.grade_spread, "open_spread", b))
        results.append(gap_rule(f"v2_total_gap_open>={b}", to, lambda r: r["pt2"] - r["open_total"], v1.grade_total, "open_total", b))
    # situational, model-free, graded at close
    fade = []
    for r in sp:
        if r["b2b_h"] and not r["b2b_a"] and r["rest_a"] >= 2:
            fade.append((r["season"], v1.grade_spread(r, -1, r["close_spread"])))
        elif r["b2b_a"] and not r["b2b_h"] and r["rest_h"] >= 2:
            fade.append((r["season"], v1.grade_spread(r, 1, r["close_spread"])))
    results.append(v1.summarize("fade_b2b_vs_rested_close", fade))
    results.append(v1.summarize("under_both_b2b_close", [(r["season"], v1.grade_total(r, -1, r["close_total"])) for r in tt if r["b2b_h"] and r["b2b_a"]]))

    # moneyline with v2 margin
    ml_rows = [r for r in hold if r["home_ml"] is not None]
    stake = profit = 0.0
    by: dict = {}
    for r in ml_rows:
        ph = v1.norm_cdf(r["pm2"] / v1.MARGIN_SIGMA)
        ih, ia = 1 / v1.american_dec(r["home_ml"]), 1 / v1.american_dec(r["away_ml"])
        nh = ih / (ih + ia)
        for mp, mk, price, won in ((ph, nh, r["home_ml"], r["home_pts"] > r["away_pts"]),
                                   (1 - ph, 1 - nh, r["away_ml"], r["away_pts"] > r["home_pts"])):
            if mp - mk >= 0.04:
                pnl = (v1.american_dec(price) - 1) if won else -1.0
                stake += 1
                profit += pnl
                a = by.setdefault(r["season"], [0.0, 0])
                a[0] += pnl
                a[1] += 1
    ml = {"rule": "v2_ml_edge>=0.04", "n": int(stake), "roi": profit / stake if stake else None,
          "seasons_positive": sum(1 for s in v1.HOLDOUT if s in by and by[s][0] > 0)}

    total_tests = V1_TESTS + len(results) + 1
    alpha = 0.05 / total_tests
    lines = ["NBA_RATINGS_V2_REST_BACKTEST_SUMMARY",
             f"base v1 params k={params.k} carry={params.carry} k_league={params.k_league}",
             f"rest coefs (fit on {v1.TUNE} only): margin c0,c_b2b,c_rest={[round(x, 3) for x in cm]} | total d0,d_b2b={[round(x, 3) for x in ct]}",
             f"b2b share of holdout team-games: {sum(r['b2b_h'] + r['b2b_a'] for r in hold) / (2 * len(hold)):.1%}",
             f"margin MAE v1 {mae([r['home_pts']-r['away_pts']-r['pm'] for r in sp]):.2f} | v2 {mae([r['home_pts']-r['away_pts']-r['pm2'] for r in sp]):.2f} | close {mae([r['home_pts']-r['away_pts']+r['close_spread'] for r in sp]):.2f}",
             f"total  MAE v1 {mae([r['home_pts']+r['away_pts']-r['pt'] for r in tt]):.2f} | v2 {mae([r['home_pts']+r['away_pts']-r['pt2'] for r in tt]):.2f} | close {mae([r['home_pts']+r['away_pts']-r['close_total'] for r in tt]):.2f}",
             f"rules (breakeven {v1.BREAKEVEN:.2%}; tests v1 {V1_TESTS} + v2 {total_tests - V1_TESTS}; gate n>=200, p<{alpha:.4f}, >=5/7 seasons):"]
    validated = []
    for x in results:
        ok = x["n"] >= 200 and x["p"] < alpha and x["seasons_above"] >= 5
        x["validated"] = ok
        if ok:
            validated.append(x["rule"])
        hit = f"{x['hit']:.1%}" if x["hit"] is not None else "n/a"
        lines.append(f"  {x['rule']:<28} {x['w']}-{x['l']} hit {hit} p={x['p']:.3f} seasons>{x['seasons_above']}/7{'  VALIDATED' if ok else ''}")
    roi = f"{ml['roi']:+.1%}" if ml["roi"] is not None else "n/a"
    lines.append(f"  {ml['rule']:<28} n {ml['n']} ROI {roi} seasons+ {ml['seasons_positive']}/7 (needs ROI>0 in >=5/7 and is not validated by ROI alone)")
    lines.append("VALIDATED MARKETS: " + (", ".join(validated) if validated else "NONE -> every NBA output stays a LEAN, not a bet"))

    text = "\n".join(lines)
    print(text)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"params": params.__dict__, "rest_margin_coefs": cm, "rest_total_coefs": ct,
                               "rules": results, "moneyline": ml, "validated": validated,
                               "total_tests": total_tests, "summary": text}, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
