#!/usr/bin/env python3
"""Prospective-method historical CFB spread residual study; no betting authority.

Strict chronology: for heldout year S, both model and residual calibration
are fit exclusively on years earlier than S. Market line is from a separately
cached historical reference, NOT a proven executable DraftKings quote.
Uses the existing frozen SDV model family, alpha and prior-game weight.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

FAMILY = "PRIOR_CURRENT_BLEND"
ALPHA = 300.0
CONSTANTS = {"prior_equivalent_games":4}
THRESHOLD = 0.5 # frozen spread challenger threshold (#1602)
FIRST_TEST = 2021
BREAKEVEN = 110/210


def fit_residual(data):
    if len(data)<300 or len({x["season"] for x in data})<3:
        raise ValueError("CFB_SPREAD_CHRONO_TRAINING_INSUFFICIENT")
    xs=[r["model_margin"]+r["home_handicap"] for r in data]
    ys=[r["actual_margin"]+r["home_handicap"] for r in data]
    a=sum(xs)/len(xs); b=sum(ys)/len(ys)
    xx=sum((x-a)**2 for x in xs)
    if xx<1e-8: raise ValueError("CFB_SPREAD_CHRONO_MODEL_VARIANCE_ZERO")
    weight=sum((x-a)*(y-b) for x,y in zip(xs,ys))/xx
    offset=b-weight*a
    return {"intercept":offset,"weight":weight,"train_n":len(data),
            "last_train_season":max(r["season"] for r in data)}


def chronological_spread_predictions(rows):
    from sportsedge.sports.cfb.sportsdataverse_candidate_model import fit_native_score_model
    seasons=sorted({int(r["season"]) for r in rows})
    out={}
    for season in seasons:
        train=[r for r in rows if int(r["season"])<season]
        hold=[r for r in rows if int(r["season"])==season]
        if len(train)<300 or not hold: continue
        fit=fit_native_score_model(train,family=FAMILY,ridge_alpha=ALPHA,constants=CONSTANTS)
        for g in hold:
            h,a=fit.predict_means(g,CONSTANTS)
            gid=str(g["game_id"])
            if gid in out: raise ValueError("CFB_SPREAD_CHRONO_GAME_DUPLICATE")
            out[gid]={"season":season,"model_margin":h-a,
                      "actual_margin":float(g["home_points"])-float(g["away_points"])}
    return out


def paired_spreads(preds,cache):
    out=[]
    for year in range(2016,2026):
        archive=cache.get(f"lines_{year}") or {}
        for gid,entry in archive.items():
            p=preds.get(str(gid))
            if p is None: continue
            if p["season"]!=year:
                raise ValueError("CFB_SPREAD_CHRONO_SEASON_ID_MISMATCH")
            try: line=float(entry["spread"])
            except (KeyError,TypeError,ValueError):continue
            if not math.isfinite(line) or abs(line)>80:continue
            out.append({"game_id":str(gid),"season":year,
                        "model_margin":p["model_margin"],
                        "actual_margin":p["actual_margin"],
                        "home_handicap":line})
    return out


def grade(rows, fit, threshold=THRESHOLD):
    wins=losses=pushes=0
    direction={"home":0,"away":0}
    for r in rows:
        delta=r["model_margin"]+r["home_handicap"]
        signed=fit["intercept"]+fit["weight"]*delta
        if abs(signed)<threshold:continue
        direction["home" if signed>0 else "away"]+=1
        result=(1 if signed>0 else -1)*(r["actual_margin"]+r["home_handicap"])
        if result>0:wins+=1
        elif result<0:losses+=1
        else:pushes+=1
    n=wins+losses
    return {"games":len(rows),"wins":wins,"losses":losses,"pushes":pushes,
            "decisions":n,"win_rate":round(wins/n,5) if n else None,
            "roi_at_assumed_minus_110":round((wins*100/110-losses)/n,5) if n else None,
            "selections":direction}


def study(paired):
    folds=[]
    for year in sorted({int(r["season"]) for r in paired}):
        if year<FIRST_TEST: continue
        train=[r for r in paired if r["season"]<year]
        test=[r for r in paired if r["season"]==year]
        if not test: continue
        try:fit=fit_residual(train)
        except ValueError:continue
        if fit["last_train_season"]>=year:raise ValueError("CFB_SPREAD_CHRONO_LOOKAHEAD")
        row=grade(test,fit)
        folds.append({
            "season":year,**row,"fit":{
                "intercept":round(fit["intercept"],5),
                "weight":round(fit["weight"],5),
                "train_n":fit["train_n"],
                "max_train_season":fit["last_train_season"],
            }})
    w=sum(x["wins"] for x in folds)
    l=sum(x["losses"] for x in folds)
    n=w+l
    yr_positive=sum(x["roi_at_assumed_minus_110"] is not None
                    and x["roi_at_assumed_minus_110"]>0 for x in folds)
    roi=(w*100/110-l)/n if n else None
    # Research-only, even when retrospective screen clears: source is a
    # compiled median, not DK quote observed at execution.
    status=("RESEARCH_SCREEN_MET_NOT_FORWARD_VALIDATED"
            if n>=200 and len(folds)>=5 and yr_positive>=4
            and roi is not None and roi>=.02
            else "NO_HISTORICALLY_VERIFIED_EDGE")
    return {
        "schema":"CFB_CHRONO_SPREAD_RESIDUAL_V1",
        "status":status,"family":FAMILY,
        "backtest_reference":"RECONSTRUCTED_HISTORICAL_MARKET_CLOSE_MEDIAN_NOT_EXECUTABLE",
        "selection_threshold_points":THRESHOLD,
        "assumed_american_odds":-110,
        "pooled":{"wins":w,"losses":l,"decisions":n,
                  "win_rate":round(w/n,5) if n else None,
                  "roi_at_assumed_minus_110":round(roi,5) if roi is not None else None,
                  "positive_roi_seasons":yr_positive},
        "folds":folds,
        "authority":{"model_p":False,"bets":False,"staking":False,
                     "official":False,"forward_validated":False,"no_backfill":True}
    }


def main(argv=None):
    ap=argparse.ArgumentParser()
    ap.add_argument("--rows")
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args(argv)
    from scripts.backtest_cfb_sdv_vs_lines import load_rows
    from sportsedge.sports.cfb.cfbd_issue_cache import load_cache
    rows=load_rows(args.rows)
    predictions=chronological_spread_predictions(rows)
    market=load_cache(issue=1475)
    paired=paired_spreads(predictions,market)
    report=study(paired)
    report["source_coverage"]={
        "training_rows":len(rows),"chrono_predictions":len(predictions),
        "paired_spread_games":len(paired),"cache_issue":1475,
    }
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print("CFB_SPREAD_CHRONO_STUDY",json.dumps({
        "status":report["status"],"pooled":report["pooled"],
        "coverage":report["source_coverage"]
    },sort_keys=True))


if __name__=="__main__":
    main()
