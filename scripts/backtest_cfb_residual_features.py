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

import json
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


def fetch_team_tables(seasons, key):
    from sportsedge.sports.cfb.source import _auth, _cfbd_url, _json_get
    talent, ret, sp = {}, {}, {}
    for s in seasons:
        for name, path, params, sink, fn in (
            ("talent", "/talent", {"year": s}, talent, lambda r: float(r.get("talent"))),
            ("returning", "/player/returning", {"year": s}, ret, lambda r: float(r.get("percentPPA"))),
            ("sp_prev", "/ratings/sp", {"year": s - 1}, sp, lambda r: float(r.get("rating"))),
        ):
            try:
                data = _json_get(_cfbd_url(path, params), headers=_auth(key))
            except Exception as exc:
                print(f"FETCH_FAILED {name} {s} {type(exc).__name__}: {str(exc)[:80]}")
                continue
            for r in data or []:
                team = r.get("team") or r.get("school")
                try:
                    sink[(s, team)] = fn(r)
                except (TypeError, ValueError):
                    pass
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
        for pr, (_, spread, am) in zip(pred, [m for m, k in zip(meta, te) if k]):
            res = (1 if pr > 0 else -1) * (am + spread)
            for t in THRESH:
                if abs(pr) >= t:
                    ats[t][0 if res > 0 else 1 if res < 0 else 2] += 1
            if abs(pr) >= 1.0 and res != 0:
                rec[0 if res > 0 else 1] += 1
        per[s] = rec
    return ats, per, coefs


def pct(w, l):
    return f"{100.0 * w / (w + l):.1f}%" if w + l else "n/a"


def main(argv=None) -> int:
    key = os.environ.get("CFBD_API_KEY") or os.environ.get("SPORTSEDGE_CFBD_API_KEY") or ""
    if not key:
        raise SystemExit("CFB_SDV_CFBD_API_KEY_REQUIRED")
    bt = _load_bt()
    rows = bt.load_rows(None)
    preds = bt.loso_predictions(rows)
    seasons = sorted({p["season"] for p in preds.values()})
    lines = bt.fetch_lines(seasons, key)
    talent, ret, sp = fetch_team_tables(seasons, key)
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
        print("  by season (>=1): " + ", ".join(f"{s}:{pct(*v)}({v[0] + v[1]})" for s, v in per.items()))
        last = coefs[max(coefs)]
        print(f"  coefs (held-out {max(coefs)}): {last}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
