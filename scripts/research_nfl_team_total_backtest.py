#!/usr/bin/env python3
"""Research only: do NFL team totals beat breakeven out of sample?

Closing team-total proxy = implied team total from nflverse closing spread and
total (total/2 +/- spread/2), posted at the nearest half point like DK.
Tests (all strictly prior information, walk-forward refit each season):
  A) EWMA offense/defense residual (points - implied) adjustment, alpha grid.
  B) Bet toward the unrounded implied total when the posted half-point line is
     0.25 away (the "rounding" edge).
Run:  python scripts/research_nfl_team_total_backtest.py --games nfldata/data/games.csv
NOT Model_P / NOT Truth Gate / NOT OFFICIAL
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

BREAKEVEN = 0.524


def team_rows(path: str) -> pd.DataFrame:
    g = pd.read_csv(path)
    g = g[g.home_score.notna() & g.spread_line.notna() & g.total_line.notna() & (g.season >= 2006)]
    g = g.sort_values(["gameday", "game_id"]).reset_index(drop=True)
    rows = []
    for r in g.itertuples():
        h_itt = r.total_line / 2 + r.spread_line / 2  # spread_line > 0 = home favored
        for side, team, opp, itt, pts in (
            ("home", r.home_team, r.away_team, h_itt, r.home_score),
            ("away", r.away_team, r.home_team, r.total_line - h_itt, r.away_score),
        ):
            rows.append(dict(game_id=r.game_id, season=r.season, team=team, opp=opp, itt=itt, pts=pts))
    t = pd.DataFrame(rows)
    t["L"] = np.round(t.itt * 2) / 2
    return t


def grade(pts: float, line: float, side: str) -> float:
    if pts == line:
        return np.nan
    return float((pts > line) == (side == "O"))


def ewma(t: pd.DataFrame, alpha: float, carry: float = 0.5) -> np.ndarray:
    off: dict = {}
    de: dict = {}
    last: dict = {}
    fo, fd = [], []
    for _, grp in t.groupby("game_id", sort=False):
        recs = grp.to_dict("records")
        for r in recs:
            for name, d in (("o", off), ("d", de)):
                for k in (r["team"], r["opp"]):
                    if k in d and last.get((name, k)) != r["season"]:
                        d[k] *= carry
                    last[(name, k)] = r["season"]
        for r in recs:
            fo.append(off.get(r["team"], 0.0))
            fd.append(de.get(r["opp"], 0.0))
        for r in recs:
            res = r["pts"] - r["itt"]
            off[r["team"]] = (1 - alpha) * off.get(r["team"], 0.0) + alpha * res
            de[r["opp"]] = (1 - alpha) * de.get(r["opp"], 0.0) + alpha * res
    return np.c_[fo, fd]


def report(label: str, d: pd.DataFrame) -> None:
    d = d.dropna(subset=["w"])
    for per, m in (("2012-17", (d.season >= 2012) & (d.season <= 2017)), ("2018-26 OOS", d.season >= 2018)):
        q = d[m]
        hr = q.w.mean() if len(q) else float("nan")
        print(f"{label:28s} {per:12s} hit {hr:.3f} n={len(q):5d} {'BEATS' if hr > BREAKEVEN else 'below'} {BREAKEVEN}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", required=True)
    args = ap.parse_args()
    t = team_rows(args.games)
    y = (t.pts - t.itt).values
    for alpha in (0.05, 0.1, 0.2):
        X = ewma(t, alpha)
        adj = np.full(len(t), np.nan)
        for s in range(2012, int(t.season.max()) + 1):
            tr = (t.season < s).values
            te = (t.season == s).values
            coef = np.linalg.lstsq(X[tr], y[tr], rcond=None)[0]
            adj[te] = X[te] @ coef
        for th in (0.25, 0.5):
            d = t[np.abs(adj) >= th].copy()
            side = np.where(adj[np.abs(adj) >= th] > 0, "O", "U")
            d["w"] = [grade(p, l, s) for p, l, s in zip(d.pts, d.L, side)]
            report(f"A ewma a={alpha} |adj|>={th}", d)
    d = t[(t.L - t.itt).abs() >= 0.25].copy()
    side = np.where(d.L < d.itt, "O", "U")
    d["w"] = [grade(p, l, s) for p, l, s in zip(d.pts, d.L, side)]
    report("B rounding direction", d)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
