"""NFL totals, simple engine: can results-based scoring ratings beat the book's closing total?

Own view: each team gets an offense and a defense rating, fit by weighted ridge least squares to past
points scored (home pts ~ mu + hfa + off[home] + def[away]; away pts ~ mu + off[away] + def[home]).
Predicted total = sum of both. Bet OVER/UNDER when own total differs from the closing total by >= THR,
at the actual closing over/under price. Settings picked on 2010-2019, frozen, tested once on 2020-2026.
Usage: python totals_nfl.py games.csv   (nflverse schedules games.csv)
"""
import sys, math
import numpy as np, pandas as pd

TRAIN, TEST = range(2010, 2020), range(2020, 2027)


def dec(o):
    o = float(o); return 1 + (o / 100 if o > 0 else 100 / -o)


def load(p):
    g = pd.read_csv(p)
    g = g[(g.game_type == "REG")].dropna(subset=["total_line"]).copy()
    g["neutral"] = g.location.eq("Neutral")
    g["t"] = g.season * 100 + g.week
    return g.sort_values(["season", "week"])


def fit(past, wts, ridge):
    teams = sorted(set(past.home_team) | set(past.away_team)); ix = {t: i for i, t in enumerate(teams)}; n = len(teams)
    rows, y, w = [], [], []
    for (h, a, hs, as_, nt), wt in zip(past[["home_team", "away_team", "home_score", "away_score", "neutral"]].itertuples(index=False), wts):
        r = np.zeros(2 * n + 2); r[0] = 1; r[1] = 0 if nt else 1; r[2 + ix[h]] = 1; r[2 + n + ix[a]] = 1; rows.append(r); y.append(hs); w.append(wt)
        r = np.zeros(2 * n + 2); r[0] = 1; r[2 + ix[a]] = 1; r[2 + n + ix[h]] = 1; rows.append(r); y.append(as_); w.append(wt)
    X, y, w = np.array(rows), np.array(y), np.sqrt(np.array(w))
    R = np.sqrt(ridge) * np.eye(2 * n + 2); R[0, 0] = R[1, 1] = 0
    sol, *_ = np.linalg.lstsq(np.vstack([X * w[:, None], R]), np.concatenate([y * w, np.zeros(2 * n + 2)]), rcond=None)
    return sol, ix, n


def predict(sol, ix, n, h, a, nt):
    o = lambda t: sol[2 + ix[t]] if t in ix else 0.0
    d = lambda t: sol[2 + n + ix[t]] if t in ix else 0.0
    return 2 * sol[0] + (0 if nt else sol[1]) + o(h) + d(a) + o(a) + d(h)


def walk(g, seasons, hl, ridge):
    out = []
    for (s, wk), cur in g[g.season.isin(seasons)].groupby(["season", "week"]):
        past = g[g.season.between(s - 1, s) & (g.t < s * 100 + wk) & g.result.notna()]
        if len(past) < 60:
            continue
        wts = 0.5 ** (((s - past.season) * 18 + (wk - past.week)) / hl)
        sol, ix, n = fit(past, wts, ridge)
        for x in cur.itertuples():
            out.append(dict(season=s, week=wk, close=x.total_line, total=x.total,
                            own=predict(sol, ix, n, x.home_team, x.away_team, x.neutral),
                            o_odds=x.over_odds, u_odds=x.under_odds))
    return pd.DataFrame(out)


def grade(df, thr):
    df = df.dropna(subset=["total"])
    gap = df.own - df.close
    b = df[gap.abs() >= thr]
    over = gap[b.index] > 0
    odds = b.o_odds.where(over, b.u_odds).fillna(-110)
    won = (b.total > b.close) & over | (b.total < b.close) & ~over
    push = b.total == b.close
    prof = won * odds.map(dec).sub(1) - (~won & ~push)
    n = int((~push).sum())
    return dict(n=n, win=float(won[~push].mean()) if n else float("nan"), roi=float(prof.sum() / len(b)) if len(b) else float("nan"),
                over_share=float(over.mean()) if len(b) else float("nan"))


def main(p):
    g = load(p); best = None
    print("TRAIN grid (2010-2019):")
    for hl in (4, 8, 16):
        for ridge in (2.0, 8.0, 32.0):
            tr = walk(g, TRAIN, hl, ridge)
            mae_own = (tr.own - tr.total).abs().mean(); mae_mkt = (tr.close - tr.total).abs().mean()
            for thr in (2.0, 3.0, 4.0):
                r = grade(tr, thr)
                print(f"  hl={hl:>2} ridge={ridge:>4} thr={thr}  MAE own={mae_own:.2f} mkt={mae_mkt:.2f}  n={r['n']:>4} win={r['win']:.3f} roi={r['roi']:+.3f}")
                if r["n"] >= 300 and (best is None or r["roi"] > best[0]):
                    best = (r["roi"], hl, ridge, thr)
    _, hl, ridge, thr = best
    te = walk(g, TEST, hl, ridge); r = grade(te, thr)
    done = te.dropna(subset=["total"])
    print(f"\nFROZEN hl={hl} ridge={ridge} thr={thr}")
    print(f"TEST 2020-2026: n={r['n']} win={r['win']:.3f} roi={r['roi']:+.3f} over_share={r['over_share']:.2f}  "
          f"MAE own={(done.own-done.total).abs().mean():.2f} mkt={(done.close-done.total).abs().mean():.2f}")
    print(f"  breakeven at -110 is 0.524; 95% band on win rate ~ +/-{1.96*math.sqrt(0.25/max(r['n'],1)):.3f}")
    # this week's open games
    s, wk = 2026, int(g[(g.season == 2026) & g.result.isna()].week.min())
    past = g[g.season.between(s - 1, s) & (g.t < s * 100 + wk) & g.result.notna()]
    sol, ix, n = fit(past, 0.5 ** (((s - past.season) * 18 + (wk - past.week)) / hl), ridge)
    print(f"\nWeek {wk} open games (gap >= {thr} = pick):")
    for x in g[(g.season == s) & (g.week == wk) & g.result.isna()].itertuples():
        own = predict(sol, ix, n, x.home_team, x.away_team, x.neutral); gap = own - x.total_line
        side = "OVER" if gap > 0 else "UNDER"; odds = x.over_odds if gap > 0 else x.under_odds
        print(f"  {x.away_team}@{x.home_team} {x.gameday} {x.gametime}ET close={x.total_line} own={own:.1f} gap={gap:+.1f} {side} ({odds:+.0f}) {'PICK' if abs(gap)>=thr else ''}")


if __name__ == "__main__":
    main(sys.argv[1])
