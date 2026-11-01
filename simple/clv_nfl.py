"""NFL early-line / CLV test: bet the May lookahead opener, check line movement and ATS.

Data: nflverse/nfldata data/initial_lines.csv (Westgate 2021 lookahead openers, the only
season it has) + data/games.csv (closing spread_line, results).
Settings are the ones already frozen by backtest_nfl.py on 2010-19 (half-life 16,
ridge 2 [x4 for results], gap >= 3). Nothing is re-tuned here; this is one run.
Point-in-time: openers were posted before the 2021 season, so ratings use 2020 regular-season
games only (results view and market-close view). Graded at -110 (no opener prices in source).
Usage: python clv_nfl.py games.csv initial_lines.csv
"""
import sys, math
import pandas as pd
import ratings
from odds import american_to_decimal

HL, RIDGE, THR, SEASON = 16, 2.0, 3.0, 2021


def main(gpath, opath):
    g = pd.read_csv(gpath)
    g = g[g.game_type == "REG"].copy()
    g["neutral"] = g.location.eq("Neutral")
    op = pd.read_csv(opath)
    op = op[(op.type == "SPREAD") & (op.season == SEASON)]
    cur = g[g.season == SEASON].copy()
    # opener in nflverse convention (positive = home favoured): -(home side's line)
    home_line = op.merge(cur[["game_id", "home_team"]], left_on="about", right_on="game_id")
    home_line = home_line[home_line.side == home_line.home_team].set_index("about").line
    cur["open"] = -cur.game_id.map(home_line)
    missing = int(cur.open.isna().sum())
    cur = cur.dropna(subset=["open", "spread_line", "result"])
    past = g[(g.season == SEASON - 1) & g.result.notna()]
    wts = 0.5 ** ((18 + 1 - past.week) / HL)
    mr, mh = ratings.fit(list(zip(past.home_team, past.away_team, past.spread_line, wts, past.neutral)), ridge=RIDGE)
    rr, rh = ratings.fit(list(zip(past.home_team, past.away_team, past.result, wts, past.neutral)), ridge=RIDGE * 4)
    cur["mkt"] = [ratings.predict(mr, mh, h, a, n) for h, a, n in zip(cur.home_team, cur.away_team, cur.neutral)]
    cur["res"] = [ratings.predict(rr, rh, h, a, n) for h, a, n in zip(cur.home_team, cur.away_team, cur.neutral)]
    print(f"games with opener+close+result: {len(cur)} (dropped {missing} with no opener)")
    print(f"copy-the-book: MAE(market-ratings vs opener) = {(cur.mkt-cur.open).abs().mean():.2f} pts")
    print(f"MAE vs result: opener {(cur.open-cur.result).abs().mean():.2f}, close {(cur.spread_line-cur.result).abs().mean():.2f}, results-ratings {(cur.res-cur.result).abs().mean():.2f}")
    edge = cur.res - cur.open
    b = cur[edge.abs() >= THR].copy()
    home = (edge[b.index] > 0)
    clv = (b.spread_line - b.open).where(home, b.open - b.spread_line)  # +ve = close moved our way
    m_open = b.result - b.open
    won = (m_open > 0) & home | (m_open < 0) & ~home
    push = m_open == 0
    pay = american_to_decimal(-110) - 1
    profit = won * pay - (~won & ~push) * 1.0
    n = int((~push).sum())
    print(f"\nFROZEN hl={HL} ridge={RIDGE} gap>={THR}, bet the opener at -110, season {SEASON}")
    print(f"bets={len(b)} decided={n} pushes={int(push.sum())}")
    print(f"avg CLV (close - opener, our side) = {clv.mean():+.2f} pts; moved our way {(clv>0).mean():.3f}, against {(clv<0).mean():.3f}")
    print(f"ATS at opener win={won[~push].mean():.3f}  ROI={profit.sum()/len(b):+.3f}")
    m_close = b.result - b.spread_line
    wc = (m_close > 0) & home | (m_close < 0) & ~home
    pc = m_close == 0
    print(f"same bets graded at the close: win={wc[~pc].mean():.3f} (decided {int((~pc).sum())})")
    print(f"breakeven at -110 is 0.524; 95% band ~ +/-{1.96*math.sqrt(0.25/max(n,1)):.3f}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
