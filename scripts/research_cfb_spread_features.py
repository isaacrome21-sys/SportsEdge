"""CFB spread-features research, attempts 2+ (frozen prereg cfb_spread_features_prereg_v1).

Research only, market-blind features. Target is the closing-spread residual:
    y = actual home margin - closing home margin   (closing home margin = -spread)
Model: OLS of y on feature diffs. Holdout 2021-2025 walk-forward: each season
scored by a fit on 2016..(season-1) only. Success (both required):
  1. weight w from regressing y on the out-of-sample prediction is > 0 with a
     season-clustered bootstrap 95% CI entirely above 0
  2. RMSE(close + pred) < RMSE(close alone) on the holdout
No card or guard changes.
"""
from __future__ import annotations

import json, os, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sportsedge.sports.cfb import cfbd_issue_cache as C  # noqa: E402

TRAIN = list(range(2016, 2021)); HOLD = list(range(2021, 2026))

ATTEMPTS = {
    "2": ["talent_diff", "returning_diff", "sp_prior_diff"],
    "3": ["returning_diff", "sp_prior_diff"],
    "4": ["sp_prior_diff"],
}


def rows(cache):
    out = []
    for s in TRAIN + HOLD:
        lines = cache.get(f"lines_{s}") or {}
        tal, ret, sp = cache.get(f"talent_{s}") or {}, cache.get(f"returning_{s}") or {}, cache.get(f"sp_{s-1}") or {}
        for g in lines.values():
            h, a = g.get("home"), g.get("away")
            if None in (g.get("spread"), g.get("home_pts"), g.get("away_pts")):
                continue
            if h not in tal or a not in tal or h not in ret or a not in ret or h not in sp or a not in sp:
                continue
            close = -g["spread"]
            out.append({"season": s, "y": (g["home_pts"] - g["away_pts"]) - close, "close": close,
                        "talent_diff": (tal[h] - tal[a]) / 100.0,
                        "returning_diff": ret[h] - ret[a],
                        "sp_prior_diff": (sp[h] - sp[a]) / 10.0})
    return out


def ols(X, y):
    X1 = np.column_stack([np.ones(len(X)), X])
    return np.linalg.lstsq(X1, y, rcond=None)[0]


def run(data, feats, seed=7):
    preds, ys, seas = [], [], []
    for s in HOLD:
        tr = [r for r in data if r["season"] < s]; te = [r for r in data if r["season"] == s]
        if not tr or not te:
            continue
        b = ols(np.array([[r[f] for f in feats] for r in tr]), np.array([r["y"] for r in tr]))
        p = b[0] + np.array([[r[f] for f in feats] for r in te]) @ b[1:]
        preds += list(p); ys += [r["y"] for r in te]; seas += [s] * len(te)
    p, y, seas = np.array(preds), np.array(ys), np.array(seas)
    w = float(np.dot(p, y) / np.dot(p, p))
    rng = np.random.default_rng(seed); uniq = np.unique(seas); boots = []
    for _ in range(2000):
        pick = rng.choice(uniq, len(uniq), replace=True)
        idx = np.concatenate([np.where(seas == k)[0] for k in pick])
        boots.append(np.dot(p[idx], y[idx]) / np.dot(p[idx], p[idx]))
    lo, hi = np.percentile(boots, [2.5, 97.5])
    rmse_close = float(np.sqrt(np.mean(y ** 2))); rmse_aug = float(np.sqrt(np.mean((y - p) ** 2)))
    return {"features": feats, "n_holdout": int(len(y)), "weight": round(w, 4), "ci95": [round(float(lo), 4), round(float(hi), 4)],
            "rmse_close": round(rmse_close, 4), "rmse_aug": round(rmse_aug, 4),
            "pass": bool(lo > 0 and rmse_aug < rmse_close)}


def main():
    key = os.environ.get("CFBD_API_KEY") or os.environ.get("SPORTSEDGE_CFBD_API_KEY") or ""
    names = C.history_names()
    cache = C.ensure(names, key, budget=int(os.environ.get("CFB_CACHE_BUDGET", "12"))) if key else C.load_cache()
    cov = C.coverage(cache, names)
    data = rows(cache)
    res = {k: run(data, v) for k, v in ATTEMPTS.items()} if data else {}
    out = {"schema": "CFB_SPREAD_FEATURES_RESEARCH_V1", "prereg": "config/cfb_spread_features_prereg_v1.json",
           "cache_coverage": cov, "n_rows": len(data),
           "n_by_season": {s: sum(r["season"] == s for r in data) for s in TRAIN + HOLD}, "attempts": res}
    path = ROOT / "docs" / "research" / "cfb_spread_features_attempts_2_4.json"
    path.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
