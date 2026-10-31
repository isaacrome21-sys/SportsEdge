"""Walk-forward CBB (men's college basketball) spread test with the simple engine.

Same method as backtest_nfl.py:
1. Market ratings: fit power ratings to the book's past spreads (copy the book).
2. Results ratings: fit the same ratings to past final margins (own view).
3. Bet the side the results favour when the two views differ from the line by >= THRESH points.
Settings are picked on TRAIN seasons only, frozen, then run once on TEST seasons.

Data: CollegeBasketballData.com (CBBD) /lines, which carries scores plus each provider's
spread. The spread used is the provider's last recorded line (treated as the close; it is
not a certified closing capture). Spread prices are not in the feed, so every bet is
graded at -110. No data is invented: if the API fails, the script stops.

Usage:
  CBBD_API_KEY=... python simple/backtest_cbb.py fetch  out/cbb_lines.json
  python simple/backtest_cbb.py test out/cbb_lines.json
"""
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ratings  # noqa: E402
from odds import american_to_decimal  # noqa: E402

API = "https://api.collegebasketballdata.com"
SEASONS = range(2014, 2027)          # season = year the season ends
TRAIN = range(2015, 2022)            # 2014 is warm-up only
TEST = range(2022, 2027)
PROVIDERS = ["DraftKings", "ESPN BET", "Bovada", "consensus"]  # first one present wins
MAX_CALLS = 100
PRICE = -110


# ---------------------------------------------------------------- fetch
def _get(path, params, key, calls):
    if calls[0] >= MAX_CALLS:
        raise SystemExit(f"call budget {MAX_CALLS} reached; stopping")
    calls[0] += 1
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}",
                                                "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def fetch(out_path):
    key = os.environ.get("CBBD_API_KEY") or os.environ.get("CFBD_API_KEY")
    if not key:
        raise SystemExit("no CBBD_API_KEY / CFBD_API_KEY in env")
    calls = [0]
    rows = []
    for s in SEASONS:
        data = _get("/lines", {"season": s}, key, calls)
        if len(data) >= 2900:  # looks capped: refetch month by month
            data = []
            for y, m in [(s - 1, 11), (s - 1, 12), (s, 1), (s, 2), (s, 3), (s, 4)]:
                start = f"{y}-{m:02d}-01T00:00:00Z"
                ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
                end = f"{ny}-{nm:02d}-01T00:00:00Z"
                part = _get("/lines", {"season": s, "startDateRange": start,
                                       "endDateRange": end}, key, calls)
                if len(part) >= 2900:
                    raise SystemExit(f"season {s} {y}-{m:02d} still capped at {len(part)}")
                data += part
                time.sleep(0.3)
        print(f"season {s}: {len(data)} games with lines (calls so far {calls[0]})", flush=True)
        rows += data
        time.sleep(0.3)
    with open(out_path, "w") as f:
        json.dump(rows, f)
    print(f"saved {len(rows)} rows, {calls[0]} API calls")
    if rows:
        print("first record keys:", sorted(rows[0].keys()))


# ---------------------------------------------------------------- shape
def _pick_line(lines):
    by = {str(x.get("provider")): x for x in lines or [] if x.get("spread") is not None}
    for p in PROVIDERS:
        if p in by:
            return p, by[p]
    if by:
        p = sorted(by)[0]
        return p, by[p]
    return None, None


def load(path):
    raw = json.load(open(path))
    out = []
    for g in raw:
        prov, ln = _pick_line(g.get("lines"))
        hs, as_ = g.get("homeScore"), g.get("awayScore")
        if ln is None or hs is None or as_ is None:
            continue
        out.append(dict(
            id=g.get("gameId"), season=int(g["season"]),
            date=pd.Timestamp(g["startDate"]).tz_localize(None) if pd.Timestamp(g["startDate"]).tzinfo is None
            else pd.Timestamp(g["startDate"]).tz_convert(None),
            home=g["homeTeam"], away=g["awayTeam"],
            neutral=bool(g.get("neutralSite", False)),
            # CBBD spread is the home line: -7 means home favoured by 7.
            close=-float(ln["spread"]),
            open=(-float(ln["spreadOpen"]) if ln.get("spreadOpen") is not None else float("nan")),
            result=float(hs) - float(as_), provider=prov))
    g = pd.DataFrame(out).drop_duplicates("id").sort_values("date").reset_index(drop=True)
    g["wk"] = g.date.dt.to_period("W-MON").dt.start_time
    return g


# ---------------------------------------------------------------- walk-forward
def walk(g, seasons, half_life, ridge, min_games=600):
    out = []
    for wk, cur in g[g.season.isin(seasons)].groupby("wk"):
        past = g[(g.date < wk) & (g.date >= wk - pd.Timedelta(days=400))]
        if len(past) < min_games:
            continue
        age = (wk - past.date).dt.days
        wts = 0.5 ** (age / half_life)
        mr, mh = ratings.fit(list(zip(past.home, past.away, past.close, wts, past.neutral)), ridge=ridge)
        rr, rh = ratings.fit(list(zip(past.home, past.away, past.result, wts, past.neutral)), ridge=ridge * 4)
        for x in cur.itertuples():
            out.append(dict(season=x.season, date=x.date, home=x.home, away=x.away,
                            close=x.close, open=x.open, result=x.result, provider=x.provider,
                            mkt=ratings.predict(mr, mh, x.home, x.away, x.neutral),
                            res=ratings.predict(rr, rh, x.home, x.away, x.neutral)))
    return pd.DataFrame(out)


def grade(df, thresh):
    edge = df.res - df.close
    bets = df[edge.abs() >= thresh]
    if bets.empty:
        return dict(n=0, win=float("nan"), roi=float("nan"))
    home = edge[bets.index] > 0
    margin = bets.result - bets.close  # >0 home covers
    won = ((margin > 0) & home) | ((margin < 0) & ~home)
    push = margin == 0
    dec = american_to_decimal(PRICE) - 1.0
    profit = won * dec - (~won & ~push) * 1.0
    decided = ~push
    return dict(n=int(decided.sum()), win=float(won[decided].mean()),
                roi=float(profit.sum() / len(bets)))


def test(path):
    g = load(path)
    print(f"games with line+score: {len(g)}; seasons {g.season.min()}-{g.season.max()}")
    print("by season:", g.groupby("season").size().to_dict())
    print("providers:", g.provider.value_counts().to_dict())
    best = None
    print(f"\nTRAIN grid ({TRAIN.start}-{TRAIN.stop - 1}), graded at {PRICE}:")
    for hl in (15, 30, 60):
        for ridge in (2.0, 8.0):
            tr = walk(g, TRAIN, hl, ridge)
            mae = (tr.mkt - tr.close).abs().mean()
            for th in (2.0, 3.0, 4.0, 6.0):
                r = grade(tr, th)
                print(f"  hl={hl:>2}d ridge={ridge:>4} thr={th}  replicate-MAE={mae:.2f}  "
                      f"n={r['n']:>5} win={r['win']:.3f} roi={r['roi']:+.3f}")
                if r["n"] >= 1000 and (best is None or r["roi"] > best[0]):
                    best = (r["roi"], hl, ridge, th)
    if best is None:
        raise SystemExit("no TRAIN setting reached n>=1000; nothing frozen, no TEST run")
    _, hl, ridge, th = best
    te = walk(g, TEST, hl, ridge)
    mae = (te.mkt - te.close).abs().mean()
    r = grade(te, th)
    print(f"\nFROZEN pick hl={hl}d ridge={ridge} thr={th}")
    print(f"TEST {TEST.start}-{TEST.stop - 1}: replicate-MAE={mae:.2f} pts  n={r['n']} "
          f"win={r['win']:.3f} roi={r['roi']:+.3f}")
    for s in TEST:
        rs = grade(te[te.season == s], th)
        print(f"  {s}: n={rs['n']} win={rs['win']:.3f} roi={rs['roi']:+.3f}")
    se = math.sqrt(0.25 / max(r["n"], 1))
    print(f"  breakeven at -110 is 0.524; 95% band on win rate ~ +/-{1.96 * se:.3f}")
    os.makedirs("out", exist_ok=True)
    te.to_csv("out/cbb_walkforward_test.csv", index=False)


if __name__ == "__main__":
    cmd, path = sys.argv[1], sys.argv[2]
    fetch(path) if cmd == "fetch" else test(path)
