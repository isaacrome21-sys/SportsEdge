"""Benchmark test v2 (entry fixed at ENTRY_HOURS before start): DraftKings prop prices vs a sharp-book fair price (no model).

Input: mlb_props_targets.csv.gz from the MLB Props Download workflow (path as argv[1]).
Sharp reference = de-vigged two-way price from the sharpest book with BOTH sides quoted
at the same line, using each side's last quote at or before the DK quote time (no look-ahead).
Test: bet DK whenever DK decimal odds exceed sharp fair odds by >= threshold; score flat
1-unit P&L on settled outcome; date-clustered bootstrap CI (common.py, seed 20261017).
Also reports CLV: DK entry price vs the sharp close (last pre-start sharp fair).
"""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
from common import boot, verdict, MIN_BETS, MIN_CLUSTERS

SHARP = ["pinnacle", "circa", "novig", "prophetx", "sporttrade", "bookmaker"]  # priority order, fixed before scoring
THRESH = [0.0, 0.02, 0.05]
ENTRY_HOURS = 3  # DK entry = last DK quote at or before start - 3h; fixed before scoring
src = Path(sys.argv[1])
df = pd.read_csv(src, low_memory=False)
df["st"] = pd.to_datetime(df.start_time); df["t"] = pd.to_datetime(df.ts)
df = df[df.t <= df.st]
df["won"] = df.won.map({True: 1, False: 0, "True": 1, "False": 0})
key = ["game_id", "player", "market", "line"]

sh = df[df.book.isin(SHARP)].sort_values("t")
def sharp_fair(sel, side, t):
    """Fair prob of `side` at time t from the first SHARP book quoting both sides by t."""
    for b in SHARP:
        q = sel[(sel.book == b) & (sel.t <= t)]
        o = q[q.side == "over"].tail(1); u = q[q.side == "under"].tail(1)
        if len(o) and len(u):
            po, pu = 1 / o.odds.iloc[0], 1 / u.odds.iloc[0]
            p = po / (po + pu)
            return (p if side == "over" else 1 - p), b
    return None, None

dk = df[(df.book == "draftkings") & (df.t <= df.st - pd.Timedelta(hours=ENTRY_HOURS))].sort_values("t").groupby(key + ["side"]).tail(1)
shg = {k: g for k, g in sh.groupby(key)}
rows = []
for r in dk.itertuples():
    k = (r.game_id, r.player, r.market, r.line)
    if k not in shg or pd.isna(r.won):
        continue
    p_entry, b = sharp_fair(shg[k], r.side, r.t)
    p_close, _ = sharp_fair(shg[k], r.side, r.st)
    if p_entry is None:
        continue
    rows.append({"date": str(r.st.date()), "game": r.game_id, "market": r.market, "odds": r.odds,
                 "p_sharp_entry": p_entry, "p_sharp_close": p_close, "sharp_book": b, "won": int(r.won)})
R = pd.DataFrame(rows)
out = {"input": src.name, "rows_in": int(len(df)), "dk_quotes_with_sharp_pair": int(len(R)),
       "games": int(R.game.nunique()) if len(R) else 0, "dates": int(R.date.nunique()) if len(R) else 0,
       "sharp_books_used": R.sharp_book.value_counts().to_dict() if len(R) else {}, "tests": {}}
for th in THRESH:
    s = R[R.odds * R.p_sharp_entry - 1 >= th] if len(R) else R
    pnl = np.where(s.won == 1, s.odds - 1, -1.0) if len(s) else []
    ci = boot(pnl, s.date) if len(s) else None
    clv = (s.odds * s.p_sharp_close - 1).dropna() if len(s) else []
    out["tests"][f"edge>={th}"] = {"n": int(len(s)), "roi": ci,
        "clv_vs_sharp_close_mean": float(np.mean(clv)) if len(clv) else None,
        "verdict": verdict(len(s), ci) if ci else "INSUFFICIENT_DATA"}
print(json.dumps(out, indent=1, default=float))
(Path(__file__).resolve().parent / "bench_mlb_props_v2_results.json").write_text(json.dumps(out, indent=1, default=float))
