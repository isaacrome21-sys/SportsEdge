#!/usr/bin/env python3
"""Can preseason info beat the CFB closing spread? Leave-one-season-out test.

target   = actual home margin - closing market home margin
features = model-vs-market gap (SDV LOSO model), and home-minus-away diffs of
           247 talent composite, returning production (percentPPA), and the
           PRIOR season's SP+ rating -- all known before the season (no leakage).
           Each preseason diff also enters scaled by early-season weight 1/week
           so its effect can fade as the season informs the market.
Fit OLS on all other seasons, predict held-out season, bet the side the
predicted residual favors when |pred| >= T, grade ATS vs closing spread.
Evaluation only.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

THRESH = (0.5, 1.0, 1.5, 2.0, 3.0)


def _load_bt():
    import importlib.util
    spec = importlib.util.spec_from_file_location("bt", ROOT / "scripts" / "backtest_cfb_sdv_vs_lines.py")
    bt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bt)
    return bt


def cached_lines(seasons, cache):
    out = {}
    for s in seasons:
        out.update(cache.get(f"lines_{s}") or {})
    return out


def team_tables(seasons, cache):
    """talent / returning production for season s and SP+ for s-1 (preseason-known), from the cache."""
    talent, ret, sp = {}, {}, {}
    for s in seasons:
        for sink, name in ((talent, f"talent_{s}"), (ret, f"returning_{s}"), (sp, f"sp_{s - 1}")):
            for team, v in (cache.get(name) or {}).items():
                sink[(s, team)] = v
    return talent, ret, sp


def build(preds, lines, talent, ret, sp):
    X, y, meta = [], [], []
    for gid, p in preds.items():
        l = lines.get(gid)
        if not l or not l.get("home") or not l.get("away"):
            continue
        s, h, a = p["season"], l["home"], l["away"]
        vals = []
        ok = True
        for tbl in (talent, ret, sp):
            hv, av = tbl.get((s, h)), tbl.get((s, a))
            if hv is None or av is None:
                ok = False
                break
            vals.append(hv - av)
        if not ok:
            continue
        wk = max(int(p.get("week") or 1), 1)
        early = 1.0 / wk
        mkt = -l["spread"]
        gap = (p["home_pred"] - p["away_pred"]) - mkt
        row = [1.0, gap] + vals + [v * early for v in vals]
        X.append(row)
        y.append((p["home_pts"] - p["away_pts"]) - mkt)
        meta.append((s, l["spread"], p["home_pts"] - p["away_pts"]))
    return np.asarray(X), np.asarray(y), meta


def loso(X, y, meta, cols):
    seasons = sorted({m[0] for m in meta})
    ats = {t: [0, 0, 0] for t in THRESH}
    per = {}
    coefs = {}
    for s in seasons:
        tr = np.array([m[0] != s for m in meta])
        te = ~tr
        Xt = X[tr][:, cols]
        beta, *_ = np.linalg.lstsq(Xt, y[tr], rcond=None)
        coefs[s] = np.round(beta, 3).tolist()
        pred = X[te][:, cols] @ beta
        rec = [0, 0]
        rec05 = [0, 0]
        for pr, (_, spread, am) in zip(pred, [m for m, k in zip(meta, te) if k]):
            res = (1 if pr > 0 else -1) * (am + spread)
            for t in THRESH:
                if abs(pr) >= t:
                    ats[t][0 if res > 0 else 1 if res < 0 else 2] += 1
            if abs(pr) >= 1.0 and res != 0:
                rec[0 if res > 0 else 1] += 1
            if abs(pr) >= 0.5 and res != 0:
                rec05[0 if res > 0 else 1] += 1
        per[s] = (rec, rec05)
    return ats, per, coefs


def pct(w, l):
    return f"{100.0 * w / (w + l):.1f}%" if w + l else "n/a"


def main(argv=None) -> int:
    key = os.environ.get("CFBD_API_KEY") or os.environ.get("SPORTSEDGE_CFBD_API_KEY") or ""
    if not key:
        raise SystemExit("CFB_SDV_CFBD_API_KEY_REQUIRED")
    from sportsedge.sports.cfb import cfbd_issue_cache as cc
    # Fill the reusable CFBD cache first (only missing items, small budget, stops on 429).
    cache = cc.ensure(cc.history_names(), key, budget=int(os.environ.get("CFB_CACHE_BUDGET", "12")))
    print("CFB_SDV_CACHE_SUMMARY " + cc.coverage(cache, cc.history_names()))
    bt = _load_bt()
    rows = bt.load_rows(None)
    preds = bt.loso_predictions(rows)
    seasons = sorted({p["season"] for p in preds.values()})
    lines = cached_lines(seasons, cache)
    talent, ret, sp = team_tables(seasons, cache)
    X, y, meta = build(preds, lines, talent, ret, sp)
    print("CFB_RESIDUAL_FEATURES_SUMMARY")
    print(f"games with lines + talent + returning + prior SP+: {len(y)} (talent {len(talent)}, ret {len(ret)}, sp {len(sp)} team-seasons)")
    specs = {
        "model gap only": [0, 1],
        "preseason only": [0, 2, 3, 4, 5, 6, 7],
        "model + preseason": [0, 1, 2, 3, 4, 5, 6, 7],
    }
    for name, cols in specs.items():
        ats, per, coefs = loso(X, y, meta, cols)
        print(f"== {name} ==")
        print("  ATS vs CLOSE by |pred residual|: " + "; ".join(f">={t}:{w}-{l} {pct(w, l)}" for t, (w, l, p) in ats.items()))
        print("  by season (>=1): " + ", ".join(f"{s}:{pct(*v[0])}({v[0][0] + v[0][1]})" for s, v in per.items()))
        print("  by season (>=0.5): " + ", ".join(f"{s}:{pct(*v[1])}({v[1][0] + v[1][1]})" for s, v in per.items()))
        last = coefs[max(coefs)]
        print(f"  coefs (held-out {max(coefs)}): {last}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
