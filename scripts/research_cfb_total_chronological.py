#!/usr/bin/env python3
"""Chronological CFB totals residual challenger, research ONLY.

The underlying SDV score model is refitted using seasons strictly earlier than
each prediction season. A market residual correction for holdout season S is
estimated exclusively from earlier seasons' *out-of-season* predictions and
their historical close/outcomes. No held-out outcomes enter its fit. The
historical closing quote is a benchmark, NOT evidence that the same line/price
was actually bettable. This script never changes serving probabilities or
creates official wagers.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

PRIMARY_THRESHOLD = 2.0   # frozen before evaluation
BREAKEVEN_MINUS_110 = 110.0 / 210.0
FAMILY = "PRIOR_CURRENT_BLEND"
RIDGE_ALPHA = 300.0
PRIOR_GAMES = 4
FIRST_RESIDUAL_VALIDATION = 2021
PROVENANCE = "RECONSTRUCTED_HISTORICAL_NOT_PIT"


def _valid(value):
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def fit_residual(train):
    """OLS market residual correction: actual-close = b + w*(model-close).

    Train uses only out-of-season predictions before the target season.
    No threshold search, no choice of season after seeing evaluation.
    """
    if len(train) < 300 or len({int(r["season"]) for r in train}) < 3:
        raise ValueError("CFB_TOTAL_CALIBRATION_HISTORY_INSUFFICIENT")
    xs = [r["model_total"] - r["closing_total"] for r in train]
    ys = [r["realized_total"] - r["closing_total"] for r in train]
    xm, ym = sum(xs) / len(xs), sum(ys) / len(ys)
    xx = sum((x-xm)**2 for x in xs)
    xy = sum((x-xm)*(y-ym) for x,y in zip(xs,ys))
    if xx <= 1e-9:
        raise ValueError("CFB_TOTAL_CALIBRATION_FEATURE_VARIANCE_ZERO")
    w = xy / xx
    b = ym - w*xm
    if not all(map(math.isfinite, (b,w))):
        raise ValueError("CFB_TOTAL_CALIBRATION_FIT_NONFINITE")
    return {"intercept": b, "weight": w, "train_n": len(train),
            "max_train_season": max(int(r["season"]) for r in train)}


def paired_rows(predictions, history):
    """Join by exact game ID; never mix opening and closing numbers."""
    out=[]
    for game_id,p in predictions.items():
        market=history.get(str(game_id))
        if not isinstance(market,dict):
            continue
        total = _valid(market.get("total"))
        predicted = _valid(p.get("home_pred"))
        away_pred = _valid(p.get("away_pred"))
        home_pts = _valid(p.get("home_pts"))
        away_pts = _valid(p.get("away_pts"))
        if any(x is None for x in (total,predicted,away_pred,home_pts,away_pts)):
            continue
        if not (10 <= total <= 120):
            continue
        out.append({
            "game_id": str(game_id), "season": int(p["season"]),
            "model_total": predicted+away_pred,
            "closing_total": total,
            "realized_total": home_pts+away_pts,
        })
    return out


def evaluate_season(rows, b, w, threshold=PRIMARY_THRESHOLD):
    """Grade at historical CLOSE as a research upper-bound proxy, -110 assumed."""
    win=loss=push=0
    raw_abs=market_abs=adjusted_abs=0.0
    directions={"over":0,"under":0}
    for r in rows:
        raw=r["model_total"]-r["closing_total"]
        actual=r["realized_total"]-r["closing_total"]
        adjusted=b+w*raw
        raw_abs += abs(r["model_total"]-r["realized_total"])
        market_abs += abs(actual)
        adjusted_abs += abs(adjusted-actual)
        if abs(adjusted) < threshold:
            continue
        directions["over" if adjusted>0 else "under"]+=1
        diff=(1 if adjusted>0 else -1)*actual
        if diff > 0: win+=1
        elif diff < 0: loss+=1
        else: push+=1
    decisions=win+loss
    return {
        "games":len(rows),
        "raw_model_total_mae": round(raw_abs/len(rows),4) if rows else None,
        "close_total_mae": round(market_abs/len(rows),4) if rows else None,
        "adjusted_total_mae":round(adjusted_abs/len(rows),4) if rows else None,
        "wins":win,"losses":loss,"pushes":push,
        "decisions":decisions,
        "roi_at_assumed_minus_110": round((win*100.0/110.0-loss)/decisions,5) if decisions else None,
        "win_rate": round(win/decisions,5) if decisions else None,
        "selections": directions,
    }


def walkforward(paired):
    seasons=sorted({int(r["season"]) for r in paired})
    if len(seasons)!=len(set(seasons)):
        raise ValueError("CFB_TOTAL_DUPLICATE_SEASONS")
    per_season=[]
    evaluated=[]
    for season in seasons:
        if season < FIRST_RESIDUAL_VALIDATION:
            continue
        train=[r for r in paired if r["season"]<season]
        test=[r for r in paired if r["season"]==season]
        if not test:
            continue
        try:
            fit=fit_residual(train)
        except ValueError:
            continue
        assert fit["max_train_season"] < season
        outcome=evaluate_season(test,fit["intercept"],fit["weight"])
        per_season.append({
            "season":season,"fit":{"intercept":round(fit["intercept"],6),
            "weight":round(fit["weight"],6),
            "train_n":fit["train_n"],"max_train_season":fit["max_train_season"]},
            **outcome,
            "mean_raw_minus_close":round(
                sum(x["model_total"]-x["closing_total"] for x in test)/len(test),3),
            "mean_raw_minus_actual":round(
                sum(x["model_total"]-x["realized_total"] for x in test)/len(test),3),
        })
        evaluated.extend((r, fit) for r in test)
    # Pool the underlying W/L rather than averages of seasonal percentage.
    wins=sum(x["wins"] for x in per_season)
    losses=sum(x["losses"] for x in per_season)
    n=wins+losses
    roi=(wins*100.0/110.0-losses)/n if n else None
    years_positive=sum((x["roi_at_assumed_minus_110"] or -1)>0 for x in per_season)
    status="BLOCKED_NO_HISTORICAL_VALIDATION"
    # An intentionally demanding, precommitted evidence screen. STILL research-only
    # because close is not an executable quote, and model was already explored.
    if n>=200 and len(per_season)>=5 and years_positive>=4 and roi is not None and roi>=0.02:
        status="RESEARCH_HISTORICAL_SCREEN_MET_NOT_FORWARD_VALIDATED"
    return {
        "schema":"CFB_SDV_TOTAL_RESIDUAL_CHRONO_V1",
        "status":status,
        "model_family":FAMILY,
        "historical_provenance":PROVENANCE,
        "market_reference":"HISTORICAL_CLOSE_NOT_EXECUTABLE_DK_SNAPSHOT",
        "method":"STRICTLY_EARLIER_SEASON_MODEL_AND_RESIDUAL_FITS",
        "threshold_points":PRIMARY_THRESHOLD,
        "assumed_american_odds":-110,
        "pooled":{"wins":wins,"losses":losses,"decisions":n,
                  "win_rate":round(wins/n,5) if n else None,
                  "roi_at_assumed_minus_110":round(roi,5) if roi is not None else None,
                  "positive_roi_seasons":years_positive,
                  "evaluated_seasons":len(per_season)},
        "per_season":per_season,
        "authority":{"model_p":False,"bets":False,"staking":False,"promotion":False,
                     "validated_positive_ev":False,"no_backfill":True},
    }


def chronological_predictions(rows):
    """Refit frozen model family on *only earlier* seasons for each held-out year."""
    from sportsedge.sports.cfb.sportsdataverse_candidate_model import fit_native_score_model
    constants={"prior_equivalent_games":PRIOR_GAMES}
    years=sorted({int(x["season"]) for x in rows})
    preds={}
    for year in years:
        training=[r for r in rows if int(r["season"])<year]
        heldout=[r for r in rows if int(r["season"])==year]
        if len(training)<300 or not heldout:
            continue
        model=fit_native_score_model(training,family=FAMILY,
                                     ridge_alpha=RIDGE_ALPHA,constants=constants)
        for r in heldout:
            h,a=model.predict_means(r,constants)
            gid=str(r["game_id"])
            if gid in preds:
                raise ValueError("CFB_TOTAL_CHRONO_GAME_ID_DUPLICATE")
            preds[gid]={"season":year,"home_pred":h,"away_pred":a,
                        "home_pts":r["home_points"],"away_pts":r["away_points"]}
    return preds


def main(argv=None):
    ap=argparse.ArgumentParser()
    ap.add_argument("--rows",help="Optional saved historical training rows")
    ap.add_argument("--lines",help="Optional saved historical line JSON")
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args(argv)
    from scripts import backtest_cfb_sdv_vs_lines as bt
    rows=bt.load_rows(args.rows)
    preds=chronological_predictions(rows)
    if args.lines:
        market=json.loads(Path(args.lines).read_text(encoding="utf-8"))
    else:
        from sportsedge.sports.cfb.cfbd_issue_cache import load_cache
        cache=load_cache(issue=1475)
        market={}
        for year in range(2016,2026):
            market.update(cache.get(f"lines_{year}") or {})
    paired=paired_rows(preds,market)
    report=walkforward(paired)
    report["source_summary"]={"historical_rows":len(rows),"chrono_predictions":len(preds),
                              "paired_closing_games":len(paired)}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print("CFB_TOTAL_CHRONO_SCREEN",json.dumps({
        "status":report["status"],"pooled":report["pooled"],"source":report["source_summary"]
    },sort_keys=True))


if __name__=="__main__":
    main()
