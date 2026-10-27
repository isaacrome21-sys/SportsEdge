#!/usr/bin/env python3
"""Walk-forward evaluation of the two repo CFB constructions vs SDV closes.

Constructions (reproduced exactly; no tuning anywhere in this file):
  AM  flat-prior capped ratings, pre-#2537 artifacts/free_models.py
      context_for: rating = clamp(mean of last-5 margins * 0.12, -3, +3);
      score means 28 +/- HFA/2 + rating; requires >=1 prior game per team.
  PM  CFB_MATCHUP_OFF_DEF_V1 / CFB_OPPONENT_ADJUSTED_V1 (current main
      context_for CFB branch; identical to scripts/backtest_cfb_matchup_blend.py
      project(), whose equivalence with the PM implementation here is covered
      by tests/test_cfb_sdv_closes.py): last-5 opponent-adjusted off/def,
      3-game shrinkage toward 28, HFA 2.5; requires >=3 prior games per team.

Protocol: within-season walk-forward; games grouped by exact kickoff
instant; projections use only games at strictly earlier instants of the same
season. Features are prior scores only (injuries/weather are zeroed, as in
the Oct 24, 2026 SBR replay: the live providers serve them as-of today only).

Labeling rules (owner, Oct 26, 2026): the SDV file carries no prices and no
timestamps. Every ROI figure is under a flat -110 ASSUMPTION and is keyed
`roi_flat_minus110_assumption`. Line comparisons are vs-close only; nothing
in this output is verified CLV. Pushes are excluded from ROI and cover-rate
denominators (stated convention; pushes are counted and reported).

Usage:
  python scripts/collect_cfb_sdv_closes.py --out-dir output/cfb_sdv_closes
  python scripts/evaluate_cfb_sdv_closes.py [--data-dir output/cfb_sdv_closes]
"""
from __future__ import annotations

import argparse
import json
import math
import numbers
import sys

import numpy as np
from collections import defaultdict
from pathlib import Path

import pandas as pd

BASE, HFA = 28.0, 2.5
WINDOW, SHRINK = 5, 3
SD_MARGIN_PROD, SD_TOTAL_PROD = 19.0, 18.5  # PRIORS["CFB"] in free_models.py
SD_MARGIN_LANE, SD_TOTAL_LANE = 15.5, 15.0  # backtest_cfb_matchup_blend.py
BANDS = [0, 3, 5, 7, 10]
CAL_BANDS = [(0, 3), (3, 5), (5, 7), (7, 10), (10, 15), (15, float("inf"))]
WIN_PAYOFF = 100.0 / 110.0  # flat -110 ASSUMPTION


def phi(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def project_season(games):
    """Yield (game, am_margin, am_total, pm_margin, pm_total); None = no
    projection. `games` are dicts sorted by kickoff instant, one season."""
    hist = defaultdict(list)  # team_id -> [(pf, pa, opp_id, opp_n_at_game)]

    def avg(team, upto=None):
        h = hist[team] if upto is None else hist[team][:upto]
        h = h[-WINDOW:]
        if not h:
            return None
        return sum(x[0] for x in h) / len(h), sum(x[1] for x in h) / len(h)

    def pm_unit(team):
        recent = hist[team][-WINDOW:]
        if len(recent) < 3:
            return None
        offs, defs = [], []
        for pf, pa, opp, opp_n in recent:
            o = avg(opp, opp_n)
            if o:
                offs.append(pf - (o[1] - BASE))
                defs.append(pa - (o[0] - BASE))
            else:
                offs.append(pf)
                defs.append(pa)
        n = len(recent)
        return ((sum(offs) + BASE * SHRINK) / (n + SHRINK),
                (sum(defs) + BASE * SHRINK) / (n + SHRINK))

    def am_rating(team):
        h = hist[team][-WINDOW:]
        if len(h) < 1:
            return None
        m = sum(x[0] - x[1] for x in h) / len(h)
        return max(-3.0, min(3.0, m * 0.12))

    pending, cur = [], None

    def flush():
        for g in pending:
            nh = len(hist[g["away_id"]])
            na = len(hist[g["home_id"]])
            hist[g["home_id"]].append((g["home_points"], g["away_points"], g["away_id"], nh))
            hist[g["away_id"]].append((g["away_points"], g["home_points"], g["home_id"], na))
        pending.clear()

    for g in games:
        if cur is not None and g["instant"] != cur:
            flush()
        cur = g["instant"]
        am_m = am_t = pm_m = pm_t = None
        rh, ra = am_rating(g["home_id"]), am_rating(g["away_id"])
        if rh is not None and ra is not None:
            hm, am_ = BASE + HFA / 2 + rh, BASE - HFA / 2 + ra
            am_m, am_t = hm - am_, hm + am_
        hu, au = pm_unit(g["home_id"]), pm_unit(g["away_id"])
        if hu and au:
            hp = hu[0] + au[1] - BASE + HFA / 2
            ap = au[0] + hu[1] - BASE - HFA / 2
            pm_m, pm_t = hp - ap, hp + ap
        yield g, am_m, am_t, pm_m, pm_t
        pending.append(g)
    flush()


def band_stats(d, gap, win):
    out = {}
    for k in BANDS:
        sel = d[d[gap] >= k] if k > 0 else d
        sel = sel[sel[win].notna()]
        w = int((sel[win] == 1).sum())
        losses = int((sel[win] == -1).sum())
        pushes = int((sel[win] == 0).sum())
        decided = w + losses
        net = w * WIN_PAYOFF - losses * 1.0
        out[f"ge{k}"] = dict(
            bets=w + losses + pushes, wins=w, losses=losses, pushes=pushes,
            cover_rate=(w / decided if decided else None),
            roi_flat_minus110_assumption=(net / decided if decided else None),
            net_units=net)
    return out


def calibration(d, gap, win, sd):
    rows = []
    for lo, hi in CAL_BANDS:
        sel = d[(d[gap] >= lo) & (d[gap] < hi) & d[win].notna() & (d[win] != 0)]
        label = f"{lo}-{hi if hi != float('inf') else '+'}"
        if len(sel) == 0:
            rows.append(dict(band=label, n=0, stated_prob=None, realized=None))
            continue
        stated = float(sum(phi(g / sd) for g in sel[gap]) / len(sel))
        realized = float((sel[win] == 1).mean())
        rows.append(dict(band=label, n=int(len(sel)), stated_prob=round(stated, 4),
                         realized=round(realized, 4),
                         gap_pp=round((stated - realized) * 100, 1)))
    return rows


def score_market(d, model_col, kind, sd_prod, sd_lane):
    d = d.copy()
    # Collector eligibility is necessary but not sufficient: reject malformed
    # direct evaluator inputs before arithmetic/aggregation can score them.
    required = (["home_team_spread", "actual_margin", model_col]
                if kind == "spread" else
                ["over_under", "actual_total", model_col])
    for field in required:
        valid = d[field].map(lambda v: (
            isinstance(v, (numbers.Real, np.integer, np.floating))
            and not isinstance(v, (bool, np.bool_))
            and math.isfinite(float(v))))
        if not bool(valid.all()):
            raise ValueError(f"NONFINITE_CFB_SCORING_INPUT: {field}")
    if kind == "spread":
        d["mkt"] = -d.home_team_spread
        d["act"] = d.actual_margin
        d["resid"] = d.actual_margin + d.home_team_spread
    else:
        d["mkt"] = d.over_under
        d["act"] = d.actual_total
        d["resid"] = d.actual_total - d.over_under
    d["model"] = d[model_col]
    d["gap"] = (d.model - d.mkt).abs()
    side_home = d.model > d.mkt
    d["win"] = [0 if r == 0 else (1 if (r > 0) == s else -1)
                for r, s in zip(d.resid, side_home)]
    d.loc[d.model == d.mkt, "win"] = float("nan")
    if d.empty:
        # Empty seasonal/market strata are NO_DATA, never NaN-bearing metrics.
        return dict(
            n=0, status="NO_DATA",
            model_mae=None, close_mae=None, model_bias=None,
            mean_abs_model_minus_close=None, mean_signed_model_minus_close=None,
            logloss_prod_sds=None, logloss_lane_sds=None,
            logloss_market_only=None,
            bands=band_stats(d, "gap", "win"),
            calibration_prod_sds=calibration(d, "gap", "win", sd_prod))
    ll = {}
    for name, sd in (("prod", sd_prod), ("lane", sd_lane)):
        tot, n = 0.0, 0
        for mdl, mkt, r in zip(d.model, d.mkt, d.resid):
            if r == 0:
                continue
            p = min(max(phi((mdl - mkt) / sd), 1e-6), 1 - 1e-6)
            y = 1 if r > 0 else 0
            tot += -(y * math.log(p) + (1 - y) * math.log(1 - p))
            n += 1
        ll[name] = (tot / n if n else None)
    return dict(
        n=int(len(d)),
        model_mae=float((d.model - d.act).abs().mean()),
        close_mae=float((d.mkt - d.act).abs().mean()),
        model_bias=float((d.model - d.act).mean()),
        mean_abs_model_minus_close=float(d.gap.mean()),
        mean_signed_model_minus_close=float((d.model - d.mkt).mean()),
        logloss_prod_sds=ll["prod"], logloss_lane_sds=ll["lane"],
        logloss_market_only=round(math.log(2), 4),
        bands=band_stats(d, "gap", "win"),
        calibration_prod_sds=calibration(d, "gap", "win", sd_prod))


def score_stratum(pred, seasons, label, both_fbs_only=False):
    d = pred[pred.season.isin(seasons)]
    if both_fbs_only:
        d = d[(d.home_div == "fbs") & (d.away_div == "fbs")]
    out = {"stratum": label, "seasons": list(seasons)}
    for model, mcol, tcol in (("AM", "am_margin", "am_total"),
                              ("PM", "pm_margin", "pm_total")):
        out[model] = {
            "spread": score_market(d[d.spread_scoreable & d[mcol].notna()],
                                   mcol, "spread", SD_MARGIN_PROD, SD_MARGIN_LANE),
            "total": score_market(d[d.total_scoreable & d[tcol].notna()],
                                  tcol, "total", SD_TOTAL_PROD, SD_TOTAL_LANE),
        }
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="output/cfb_sdv_closes")
    args = ap.parse_args(argv)
    data = Path(args.data_dir)
    closes = pd.read_csv(data / "sdv_cfb_closes_all.csv")
    results = pd.read_csv(data / "sdv_cfb_results_all.csv")
    results["instant"] = pd.to_datetime(results.start_date, utc=True, format="ISO8601")
    results = results.sort_values(["season", "instant", "game_id"])
    cmap = {int(r.game_id): r for r in closes.itertuples()}
    rows = []
    for season, gdf in results.groupby("season"):
        games = [dict(game_id=int(r.game_id), instant=r.instant,
                      home_id=int(r.home_id), away_id=int(r.away_id),
                      home_points=float(r.home_points), away_points=float(r.away_points))
                 for r in gdf.itertuples()]
        for g, am_m, am_t, pm_m, pm_t in project_season(games):
            c = cmap.get(g["game_id"])
            if c is None:
                continue
            rows.append(dict(
                season=int(season), game_id=g["game_id"], home_team=c.home_team,
                away_team=c.away_team, home_div=c.home_division, away_div=c.away_division,
                home_points=g["home_points"], away_points=g["away_points"],
                actual_margin=g["home_points"] - g["away_points"],
                actual_total=g["home_points"] + g["away_points"],
                home_team_spread=c.home_team_spread, over_under=c.over_under,
                spread_scoreable=bool(c.spread_scoreable),
                total_scoreable=bool(c.total_scoreable),
                am_margin=am_m, am_total=am_t, pm_margin=pm_m, pm_total=pm_t))
    pred = pd.DataFrame(rows)
    pred.to_csv(data / "predictions_am_pm.csv", index=False)
    results_out = {
        "primary_2023_2025": score_stratum(pred, [2023, 2024, 2025],
                                           "PRIMARY complete seasons 2023-2025"),
        "primary_2023_2026": score_stratum(pred, [2023, 2024, 2025, 2026],
                                           "PRIMARY + partial 2026 (in progress)"),
        "primary_2023_2025_both_fbs": score_stratum(
            pred, [2023, 2024, 2025], "PRIMARY 2023-2025, both-FBS only",
            both_fbs_only=True),
        "subset_2012_2022": score_stratum(
            pred, list(range(2012, 2023)),
            "SECONDARY subset 2012-2022 (core_odds_api rows only: ~110 "
            "FBS-vs-FCS games/season, NOT full-slate closes)"),
        "per_season": {str(s): score_stratum(pred, [s], f"season {s}")
                       for s in range(2012, 2027)},
    }
    (data / "metrics_am_pm.json").write_text(json.dumps(results_out, indent=1, allow_nan=False))
    for key in ("primary_2023_2025", "primary_2023_2026", "subset_2012_2022"):
        r = results_out[key]
        print(f"== {r['stratum']}")
        for model in ("AM", "PM"):
            for kind in ("spread", "total"):
                m = r[model][kind]
                b0 = m["bands"]["ge0"]
                if m["n"] == 0:
                    print(f"  {model} {kind}: n=0 NO_DATA")
                    continue
                print(f"  {model} {kind}: n={m['n']} MAE model {m['model_mae']:.2f} "
                      f"vs close {m['close_mae']:.2f} | cover(all) {b0['cover_rate']} "
                      f"ROI flat -110 ASSUMPTION "
                      f"{b0['roi_flat_minus110_assumption']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
