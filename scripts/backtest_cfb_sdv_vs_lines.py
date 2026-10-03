#!/usr/bin/env python3
"""Leave-one-season-out backtest of the PRIOR_CURRENT_BLEND CFB model vs CFBD closing lines.

For each season S in the materialized SDV training rows, refit the frozen family
(ridge alpha 300, prior_equivalent_games 4) on all other seasons and predict S.
Then join CFBD historical lines (/lines) by game_id and report ATS / total
hit rates by model-vs-line disagreement bucket. Breakeven at -110 is 52.38%.

Evaluation only. No bets, no freeze change.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ROWS_REF = "history/cfb/sportsdataverse-selection/training_rows.json"
FAMILY = "PRIOR_CURRENT_BLEND"
ALPHA = 300.0
CONSTANTS = {"prior_equivalent_games": 4}
BUCKETS = (0.0, 3.0, 5.0, 7.0, 10.0)
PROVIDER_ORDER = ("consensus", "Bovada", "DraftKings", "ESPN Bet", "William Hill (New Jersey)", "teamrankings", "numberfire")


def load_rows(path: str | None) -> list:
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    subprocess.run(["git", "fetch", "-q", "--depth", "1", "origin", "data"], check=True, cwd=ROOT)
    out = subprocess.run(["git", "show", "FETCH_HEAD:" + ROWS_REF], check=True, cwd=ROOT,
                         capture_output=True)
    return json.loads(out.stdout)


def loso_predictions(rows: list) -> dict:
    from sportsedge.sports.cfb.sportsdataverse_candidate_model import fit_native_score_model
    seasons = sorted({int(r["season"]) for r in rows})
    preds = {}
    for s in seasons:
        train = [r for r in rows if int(r["season"]) != s]
        test = [r for r in rows if int(r["season"]) == s]
        model = fit_native_score_model(train, family=FAMILY, ridge_alpha=ALPHA, constants=CONSTANTS)
        for r in test:
            h, a = model.predict_means(r, CONSTANTS)
            preds[str(r["game_id"])] = {"season": s, "week": r.get("week"), "home_pred": h, "away_pred": a,
                                        "home_pts": float(r["home_points"]), "away_pts": float(r["away_points"])}
    return preds


def fetch_lines(seasons, key: str) -> dict:
    from sportsedge.sports.cfb.source import _auth, _cfbd_url, _json_get
    out = {}
    for s in seasons:
        try:
            data = _json_get(_cfbd_url("/lines", {"year": int(s), "seasonType": "regular"}), headers=_auth(key))
        except Exception as exc:  # keep going; report coverage
            print(f"LINES_FETCH_FAILED {s} {type(exc).__name__}: {str(exc)[:100]}")
            continue
        for g in data or []:
            lines = g.get("lines") or []
            by = {str(l.get("provider")): l for l in lines}
            pick = next((by[p] for p in PROVIDER_ORDER if p in by and by[p].get("spread") is not None), None)
            if pick is None:
                pick = next((l for l in lines if l.get("spread") is not None), None)
            if pick is None:
                continue
            try:
                spread = float(pick["spread"])
                total = float(pick["overUnder"]) if pick.get("overUnder") is not None else None
            except (TypeError, ValueError):
                continue
            out[str(g.get("id"))] = {"spread": spread, "total": total, "provider": pick.get("provider")}
    return out


def evaluate(preds: dict, lines: dict) -> dict:
    ats = {b: [0, 0, 0] for b in BUCKETS}   # win, loss, push
    tot = {b: [0, 0, 0] for b in BUCKETS}
    n = 0
    err_model = err_mkt = 0.0
    terr_model = terr_mkt = 0.0
    tn = 0
    for gid, p in preds.items():
        ln = lines.get(gid)
        if not ln:
            continue
        n += 1
        pm = p["home_pred"] - p["away_pred"]
        am = p["home_pts"] - p["away_pts"]
        mkt_m = -ln["spread"]                      # CFBD spread is home handicap
        err_model += abs(pm - am)
        err_mkt += abs(mkt_m - am)
        d = pm - mkt_m
        cover = am + ln["spread"]                  # >0 home covers
        side = 1 if d > 0 else -1
        res = side * cover
        for b in BUCKETS:
            if abs(d) >= b and d != 0:
                ats[b][0 if res > 0 else 1 if res < 0 else 2] += 1
        if ln["total"] is not None:
            tn += 1
            pt = p["home_pred"] + p["away_pred"]
            at = p["home_pts"] + p["away_pts"]
            terr_model += abs(pt - at)
            terr_mkt += abs(ln["total"] - at)
            dt = pt - ln["total"]
            r2 = (1 if dt > 0 else -1) * (at - ln["total"])
            for b in BUCKETS:
                if abs(dt) >= b and dt != 0:
                    tot[b][0 if r2 > 0 else 1 if r2 < 0 else 2] += 1
    return {"games_joined": n, "margin_mae_model": err_model / max(n, 1), "margin_mae_market": err_mkt / max(n, 1),
            "total_games": tn, "total_mae_model": terr_model / max(tn, 1), "total_mae_market": terr_mkt / max(tn, 1),
            "ats": ats, "totals": tot}


BLEND_THRESHOLDS = (0.5, 1.0, 1.5, 2.0, 3.0)


def _ols(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    w = sxy / sxx if sxx > 0 else 0.0
    return my - w * mx, w


def market_anchored(preds: dict, lines: dict) -> dict:
    """LOSO: adjusted = market + b + w*(model - market); bet when |adjustment| >= T."""
    joined = []
    for gid, p in preds.items():
        ln = lines.get(gid)
        if not ln:
            continue
        joined.append((p, ln))
    seasons = sorted({p["season"] for p, _ in joined})
    out = {"spread": {"w_by_season": {}, "ats": {t: [0, 0, 0] for t in BLEND_THRESHOLDS}, "by_season": {}},
           "total": {"w_by_season": {}, "ou": {t: [0, 0, 0] for t in BLEND_THRESHOLDS}}}
    for s in seasons:
        tr = [(p, l) for p, l in joined if p["season"] != s]
        te = [(p, l) for p, l in joined if p["season"] == s]
        # spread
        xs = [(p["home_pred"] - p["away_pred"]) - (-l["spread"]) for p, l in tr]
        ys = [(p["home_pts"] - p["away_pts"]) - (-l["spread"]) for p, l in tr]
        b, w = _ols(xs, ys)
        out["spread"]["w_by_season"][s] = (round(b, 3), round(w, 4))
        season_rec = [0, 0]
        for p, l in te:
            adj = b + w * ((p["home_pred"] - p["away_pred"]) + l["spread"])
            cover = (p["home_pts"] - p["away_pts"]) + l["spread"]
            res = (1 if adj > 0 else -1) * cover
            for t in BLEND_THRESHOLDS:
                if abs(adj) >= t:
                    out["spread"]["ats"][t][0 if res > 0 else 1 if res < 0 else 2] += 1
            if abs(adj) >= 1.0 and res != 0:
                season_rec[0 if res > 0 else 1] += 1
        out["spread"]["by_season"][s] = season_rec
        # totals
        trt = [(p, l) for p, l in tr if l["total"] is not None]
        tet = [(p, l) for p, l in te if l["total"] is not None]
        if len(trt) > 50:
            xs = [(p["home_pred"] + p["away_pred"]) - l["total"] for p, l in trt]
            ys = [(p["home_pts"] + p["away_pts"]) - l["total"] for p, l in trt]
            b, w = _ols(xs, ys)
            out["total"]["w_by_season"][s] = (round(b, 3), round(w, 4))
            for p, l in tet:
                adj = b + w * ((p["home_pred"] + p["away_pred"]) - l["total"])
                res = (1 if adj > 0 else -1) * ((p["home_pts"] + p["away_pts"]) - l["total"])
                for t in BLEND_THRESHOLDS:
                    if abs(adj) >= t:
                        out["total"]["ou"][t][0 if res > 0 else 1 if res < 0 else 2] += 1
    return out


def fmt_blend(bl: dict) -> str:
    def pct(w, l):
        return f"{100.0 * w / (w + l):.1f}%" if w + l else "n/a"
    lines = ["MARKET-ANCHORED (LOSO): adj = b + w*(model - market)",
             "spread (b, w) by held-out season: " + ", ".join(f"{s}:{v}" for s, v in bl["spread"]["w_by_season"].items()),
             "ATS when |adjustment| >= T pts:"]
    for t, (w, l, p) in bl["spread"]["ats"].items():
        lines.append(f"  >= {t}: {w}-{l}-{p} hit {pct(w, l)}")
    lines.append("ATS by season at T>=1: " + ", ".join(f"{s}:{pct(*v)}({v[0]+v[1]})" for s, v in bl["spread"]["by_season"].items()))
    lines.append("total (b, w): " + ", ".join(f"{s}:{v}" for s, v in bl["total"]["w_by_season"].items()))
    lines.append("O/U when |adjustment| >= T pts:")
    for t, (w, l, p) in bl["total"]["ou"].items():
        lines.append(f"  >= {t}: {w}-{l}-{p} hit {pct(w, l)}")
    return "\n".join(lines)


def fmt(ev: dict) -> str:
    def pct(w, l):
        return f"{100.0 * w / (w + l):.1f}%" if w + l else "n/a"
    lines = [
        f"games joined to lines: {ev['games_joined']}",
        f"margin MAE  model {ev['margin_mae_model']:.2f} | market {ev['margin_mae_market']:.2f}",
        f"total  MAE  model {ev['total_mae_model']:.2f} | market {ev['total_mae_market']:.2f}",
        "ATS when model disagrees with closing spread by >= X pts (breakeven 52.4%):",
    ]
    for b, (w, l, p) in ev["ats"].items():
        lines.append(f"  >= {b:>4}: {w}-{l}-{p}  hit {pct(w, l)}")
    lines.append("TOTALS when model disagrees with closing total by >= X pts:")
    for b, (w, l, p) in ev["totals"].items():
        lines.append(f"  >= {b:>4}: {w}-{l}-{p}  hit {pct(w, l)}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows")
    ap.add_argument("--lines-json", help="offline lines map {game_id: {spread,total}} for testing")
    ap.add_argument("--output", default="artifacts/run_it/cfb_sdv_backtest.json")
    args = ap.parse_args(argv)
    rows = load_rows(args.rows)
    preds = loso_predictions(rows)
    seasons = sorted({p["season"] for p in preds.values()})
    if args.lines_json:
        lines = json.loads(Path(args.lines_json).read_text())
    else:
        key = os.environ.get("CFBD_API_KEY") or os.environ.get("SPORTSEDGE_CFBD_API_KEY") or ""
        if not key:
            raise SystemExit("CFB_SDV_CFBD_API_KEY_REQUIRED")
        lines = fetch_lines(seasons, key)
    ev = evaluate(preds, lines)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps({"family": FAMILY, "alpha": ALPHA, "seasons": seasons,
                                             "evaluation": {k: v for k, v in ev.items()}}, indent=2, default=str))
    bl = market_anchored(preds, lines)
    print("CFB_SDV_BACKTEST_SUMMARY")
    print(fmt(ev))
    print(fmt_blend(bl))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
