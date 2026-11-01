"""CBB spread + early-line (CLV) test with the simple engine, on SBR archive data.

Same engine and same pick-then-freeze procedure as backtest_cbb.py / clv_cbb.py, only the
data source differs (the CBBD API is unreachable from the Claude sandbox):

  Data: sportsbookreviewsonline.com NCAA basketball season files (Open, Close, Final per
  team), as mirrored in the public GitHub repo ajhildebrand/WinLossSequencesSpring24,
  commit 12f7b82df7dcf26af2ddade4100b5a5fe01ad088, path
  sportsbookreviewsonline/ncaa_basketball/raw_data/ncaa-basketball-YYYY-YY.csv.
  These are SBR's recorded open/close, NOT DraftKings captures and not certified closes.
  No spread prices in the files, so every bet is graded at -110.

Each game is two rows (V/H, or N/N for neutral). In each row the Open/Close cell holds
either the spread (favourite's row) or the total. The spread is the cell with the smaller
absolute value; 'pk' = 0. Games where that can't be read cleanly are dropped and counted.
Nothing is invented.

Split (season = year it ends): TRAIN 2016-2018 (first weeks are rating warm-up),
TEST 2019-2020. Settings are picked on TRAIN only (same grids and n>=1000 rule as the
CBBD scripts), frozen, then TEST is run once.

Usage: python simple/backtest_cbb_sbr.py DIR_WITH_SBR_CSVS
"""
import glob
import math
import os
import re
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest_cbb import PRICE, walk, grade as grade_close  # noqa: E402
from clv_cbb import grade as grade_open, fmt as fmt_open  # noqa: E402

TRAIN = range(2016, 2019)
TEST = range(2019, 2021)


def _num(s):
    s = str(s).strip().lower()
    if s == "pk":
        return 0.0
    try:
        v = float(s)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def _spread(a, b):
    """(cell in row 1, cell in row 2) -> (fav_row 0/1, points) or None."""
    x, y = _num(a), _num(b)
    if x is None or y is None:
        return None
    ax, ay = abs(x), abs(y)
    if min(ax, ay) >= 60 or max(ax, ay) < 60:   # need one spread and one total
        return None
    return (0, ax) if ax < ay else (1, ay)


def load_sbr(folder):
    rows, dropped = [], 0
    for path in sorted(glob.glob(os.path.join(folder, "*.csv"))):
        m = re.search(r"(\d{4})-(\d{2})", os.path.basename(path))
        y0 = int(m.group(1))
        df = pd.read_csv(path, dtype=str)
        df = df[df.VH.isin(["V", "H", "N"])].reset_index(drop=True)
        for i in range(0, len(df) - 1, 2):
            r1, r2 = df.iloc[i], df.iloc[i + 1]
            if not (r1.VH == "V" and r2.VH == "H") and not (r1.VH == "N" and r2.VH == "N"):
                dropped += 1
                continue
            c, o = _spread(r1.Close, r2.Close), _spread(r1.Open, r2.Open)
            f1, f2 = _num(r1.Final), _num(r2.Final)
            if c is None or f1 is None or f2 is None or r1.Date != r2.Date:
                dropped += 1
                continue
            mmdd = int(r1.Date)
            mo, dy = divmod(mmdd, 100)
            yr = y0 if mo >= 7 else y0 + 1
            # home = row 2; close/open = expected home margin (+ = home favoured)
            close = -c[1] if c[0] == 0 else c[1]
            opn = float("nan") if o is None else (-o[1] if o[0] == 0 else o[1])
            rows.append(dict(id=f"{yr}{mmdd:04d}-{r1.Rot}", season=y0 + 1,
                             date=pd.Timestamp(year=yr, month=mo, day=dy),
                             home=r2.Team, away=r1.Team, neutral=r1.VH == "N",
                             close=close, open=opn, result=f2 - f1, provider="SBR"))
    g = pd.DataFrame(rows).drop_duplicates("id").sort_values("date").reset_index(drop=True)
    g["wk"] = g.date.dt.to_period("W-MON").dt.start_time
    return g, dropped


def main(folder):
    g, dropped = load_sbr(folder)
    print(f"games parsed: {len(g)} (dropped {dropped} unreadable pairs); "
          f"by season {g.groupby('season').size().to_dict()}")
    have = g.open.notna()
    print(f"with an open: {int(have.sum())}; mean |open->close| = "
          f"{(g[have].close - g[have].open).abs().mean():.2f} pts")
    print(f"sanity: mean(result - close) = {(g.result - g.close).mean():+.2f}, "
          f"MAE(result vs close) = {(g.result - g.close).abs().mean():.2f}")

    walks = {}
    best_c = best_o = None
    print(f"\nTRAIN grid {TRAIN.start}-{TRAIN.stop - 1}, graded at {PRICE}")
    for hl in (15, 30, 60):
        for ridge in (2.0, 8.0):
            tr = walk(g, TRAIN, hl, ridge)
            walks[(hl, ridge)] = tr
            mae = (tr.mkt - tr.close).abs().mean()
            for th in (2.0, 3.0, 4.0, 6.0):
                r = grade_close(tr, th)
                print(f"  CLOSE hl={hl:>2} ridge={ridge:>4} thr={th} copy-MAE={mae:.2f} "
                      f"n={r['n']:>5} win={r['win']:.3f} roi={r['roi']:+.3f}")
                if r["n"] >= 1000 and (best_c is None or r["roi"] > best_c[0]):
                    best_c = (r["roi"], hl, ridge, th)
            for view in ("res", "mkt"):
                for th in (1.0, 2.0, 3.0, 4.0):
                    r = grade_open(tr, view, th)
                    print(f"  OPEN  view={view} hl={hl:>2} ridge={ridge:>4} thr={th} {fmt_open(r)}")
                    if r["n"] >= 1000 and (best_o is None or r["clv"] > best_o[0]):
                        best_o = (r["clv"], view, hl, ridge, th)

    se = lambda n: 1.96 * math.sqrt(0.25 / max(n, 1))  # noqa: E731
    print(f"\n=== TEST {TEST.start}-{TEST.stop - 1} (run once with frozen settings) ===")
    if best_c is None:
        print("CLOSE: no TRAIN setting reached n>=1000; no test run")
    else:
        _, hl, ridge, th = best_c
        te = walk(g, TEST, hl, ridge)
        r = grade_close(te, th)
        print(f"CLOSE frozen hl={hl} ridge={ridge} thr={th}: copy-MAE="
              f"{(te.mkt - te.close).abs().mean():.2f} n={r['n']} win={r['win']:.3f} "
              f"roi={r['roi']:+.3f} (breakeven 0.524, 95% band +/-{se(r['n']):.3f})")
        for s in TEST:
            rs = grade_close(te[te.season == s], th)
            print(f"  {s}: n={rs['n']} win={rs['win']:.3f} roi={rs['roi']:+.3f}")
    if best_o is None:
        print("OPEN: no TRAIN setting reached n>=1000; no test run")
    else:
        _, view, hl, ridge, th = best_o
        te = walk(g, TEST, hl, ridge)
        r = grade_open(te, view, th)
        print(f"OPEN frozen view={view} hl={hl} ridge={ridge} thr={th}: {fmt_open(r)} "
              f"(95% band +/-{se(r['n']):.3f})")
        for s in TEST:
            print(f"  {s}: {fmt_open(grade_open(te[te.season == s], view, th))}")


if __name__ == "__main__":
    main(sys.argv[1])
