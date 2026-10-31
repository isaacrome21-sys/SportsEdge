"""Walk-forward NFL spread test: can results-based ratings beat the book's closing line?

1. Market ratings are fitted to past closing spreads, which reverse-engineers the book's power ratings.
2. Results ratings are fitted to past final margins.
3. When the two disagree by >= THRESH points, bet the side the results favour,
   at the actual closing price. Grade ATS.
Parameters are picked on TRAIN seasons only and then frozen for TEST.
Usage: python backtest_nfl.py /path/to/nfldata/data/games.csv
"""
import sys
import math
import pandas as pd
import ratings
from odds import american_to_decimal

TRAIN = range(2010, 2020)
TEST = range(2020, 2027)


def load(path):
    g = pd.read_csv(path)
    g = g[g.game_type == "REG"].dropna(subset=["spread_line"]).copy()
    g["neutral"] = g.location.eq("Neutral")
    g["t"] = g.season * 100 + g.week
    return g.sort_values(["season", "week"])


def walk(g, seasons, half_life, ridge):
    out = []
    for (s, wk), cur in g[g.season.isin(seasons)].groupby(["season", "week"]):
        past = g[(g.season.between(s - 1, s)) & (g.t < s * 100 + wk) & g.result.notna()]
        if len(past) < 60:
            continue
        # age in games-weeks; previous season counts as further back
        age = (s - past.season) * 18 + (wk - past.week)
        wts = 0.5 ** (age / half_life)
        mrows = list(zip(past.home_team, past.away_team, past.spread_line, wts, past.neutral))
        rrows = list(zip(past.home_team, past.away_team, past.result, wts, past.neutral))
        mr, mh = ratings.fit(mrows, ridge=ridge)
        rr, rh = ratings.fit(rrows, ridge=ridge * 4)
        for _, x in cur.iterrows():
            out.append(dict(
                season=s, week=wk, home=x.home_team, away=x.away_team,
                close=x.spread_line, result=x.result,
                mkt=ratings.predict(mr, mh, x.home_team, x.away_team, x.neutral),
                res=ratings.predict(rr, rh, x.home_team, x.away_team, x.neutral),
                h_odds=x.home_spread_odds, a_odds=x.away_spread_odds,
            ))
    return pd.DataFrame(out)


def grade(df, thresh, w=1.0):
    """Bet when blended view differs from the close by >= thresh."""
    view = df.close + w * (df.res - df.close)
    edge = view - df.close
    bets = df[edge.abs() >= thresh].copy()
    if bets.empty:
        return dict(n=0, win=float("nan"), roi=float("nan"))
    home = edge[bets.index] > 0
    margin = bets.result - bets.close  # >0 home covers
    odds = bets.h_odds.where(home, bets.a_odds).fillna(-110)
    won = (margin > 0) & home | (margin < 0) & ~home
    push = margin == 0
    profit = won * odds.map(american_to_decimal).sub(1) - (~won & ~push) * 1.0
    decided = ~push
    return dict(n=int(decided.sum()), win=float(won[decided].mean()),
                roi=float(profit.sum() / len(bets)))


def main(path):
    g = load(path)
    best = None
    print("TRAIN grid (2010-2019):")
    for hl in (4, 8, 16):
        for ridge in (2.0, 8.0):
            tr = walk(g, TRAIN, hl, ridge)
            mae = (tr.mkt - tr.close).abs().mean()
            for th in (1.0, 2.0, 3.0):
                r = grade(tr, th)
                print(f"  hl={hl:>2} ridge={ridge:>4} thr={th}  replicate-MAE={mae:.2f}  n={r['n']:>4} win={r['win']:.3f} roi={r['roi']:+.3f}")
                if r["n"] >= 300 and (best is None or r["roi"] > best[0]):
                    best = (r["roi"], hl, ridge, th)
    _, hl, ridge, th = best
    te = walk(g, TEST, hl, ridge)
    mae = (te.mkt - te.close).abs().mean()
    r = grade(te, th)
    print(f"\nFROZEN pick hl={hl} ridge={ridge} thr={th}")
    print(f"TEST 2020-2026: replicate-MAE={mae:.2f} pts  n={r['n']} win={r['win']:.3f} roi={r['roi']:+.3f}")
    se = math.sqrt(0.25 / max(r['n'], 1))
    print(f"  breakeven at -110 is 0.524; 95% band on win rate ~ +/-{1.96*se:.3f}")
    te.to_csv("nfl_walkforward_test.csv", index=False)


if __name__ == "__main__":
    main(sys.argv[1])
