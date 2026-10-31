"""Early-line / CLV test for CBB with the simple engine.

Question: if we bet the OPENING line wherever our ratings disagree with it, does the line
then move our way by the close (CLV), and do those bets win at the opening number?

Same data and ratings as backtest_cbb.py (ratings use only games before the bet week):
  view "res" = ratings fitted to past final margins (own view)
  view "mkt" = ratings fitted to past closing lines (copy of the book's recent closes);
               a gap here means the opener is off from what the book's own closes imply.
Bet the side the view favours when |view - open| >= THRESH. Opens are as recorded by the
CBBD provider (not certified captures); bets are graded at -110 because the feed has no prices.
Settings (view, half-life, ridge, threshold) are picked on TRAIN by mean CLV with n >= 1000,
frozen, then run once on TEST. Nothing is invented: games without an open are never bet.

Usage: python simple/clv_cbb.py out/cbb_lines.json   (file made by backtest_cbb.py fetch)
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest_cbb import TRAIN, TEST, PRICE, load, walk  # noqa: E402
from odds import american_to_decimal  # noqa: E402


def grade(df, view, thresh):
    edge = df[view] - df.open
    b = df[edge.abs() >= thresh]
    if b.empty:
        return dict(n=0, clv=float("nan"), beat=float("nan"), win=float("nan"), roi=float("nan"))
    side = (edge[b.index] > 0).map({True: 1.0, False: -1.0})  # +1 = home
    clv = (b.close - b.open) * side            # points the line moved our way
    margin = (b.result - b.open) * side         # >0 our side covers the opener
    won, push = margin > 0, margin == 0
    profit = won * (american_to_decimal(PRICE) - 1.0) - (~won & ~push) * 1.0
    return dict(n=len(b), clv=float(clv.mean()), beat=float((clv > 0).mean()),
                win=float(won[~push].mean()), roi=float(profit.sum() / len(b)))


def fmt(r):
    return (f"n={r['n']:>5} avgCLV={r['clv']:+.2f}pts beat-close={r['beat']:.3f} "
            f"win@open={r['win']:.3f} roi={r['roi']:+.3f}")


def main(path):
    g = load(path)
    have = g.open.notna()
    print(f"games: {len(g)}; with an open: {int(have.sum())}")
    print("with open by season:", g[have].groupby("season").size().to_dict())
    h = g[have]
    print("open->close move: mean |move| = %.2f pts, share moved = %.3f"
          % ((h.close - h.open).abs().mean(), (h.close != h.open).mean()))
    # ratings still fit on every game; games with no open drop out in grade() (NaN edge)
    best = None
    print(f"\nTRAIN grid ({TRAIN.start}-{TRAIN.stop - 1}), pick = max avg CLV with n>=1000:")
    for hl in (15, 30, 60):
        for ridge in (2.0, 8.0):
            tr = walk(g, TRAIN, hl, ridge)
            for view in ("res", "mkt"):
                for th in (1.0, 2.0, 3.0, 4.0):
                    r = grade(tr, view, th)
                    print(f"  view={view} hl={hl:>2}d ridge={ridge:>4} thr={th}  {fmt(r)}")
                    if r["n"] >= 1000 and (best is None or r["clv"] > best[0]):
                        best = (r["clv"], view, hl, ridge, th)
    if best is None:
        raise SystemExit("no TRAIN setting reached n>=1000; nothing frozen, no TEST run")
    _, view, hl, ridge, th = best
    te = walk(g, TEST, hl, ridge)
    r = grade(te, view, th)
    print(f"\nFROZEN pick view={view} hl={hl}d ridge={ridge} thr={th}")
    print(f"TEST {TEST.start}-{TEST.stop - 1}: {fmt(r)}")
    for s in TEST:
        print(f"  {s}: {fmt(grade(te[te.season == s], view, th))}")
    se = math.sqrt(0.25 / max(r["n"], 1))
    print(f"  breakeven at -110 is 0.524; 95% band on win rate ~ +/-{1.96 * se:.3f}")
    os.makedirs("out", exist_ok=True)
    te.to_csv("out/cbb_clv_test.csv", index=False)


if __name__ == "__main__":
    main(sys.argv[1])
