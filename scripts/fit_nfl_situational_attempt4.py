#!/usr/bin/env python3
"""NFL Attempt 4: point-in-time situational features versus closing prices."""
from __future__ import annotations
import argparse, hashlib, json
from collections import defaultdict
from datetime import date
from itertools import groupby
from pathlib import Path
import numpy as np
import fit_football_baselines as base

def situational_features(games):
    ordered=sorted(games,key=lambda g:(g["date"],g["id"]))
    history=defaultdict(list); last_date={}; X=[]; ym=[]; yt=[]; dates=[]; keys=[]
    names=["home_points_for","home_points_against","away_points_for","away_points_against",
           "home_net","away_net","home_rest_days","away_rest_days","rest_diff",
           "home_short_week","away_short_week","home_extended_rest","away_extended_rest"]
    for game_date,grp in groupby(ordered,key=lambda g:g["date"]):
        batch=list(grp)
        current=date.fromisoformat(game_date)
        for g in batch:
            h,a=g["home"],g["away"]
            if len(history[h])<5 or len(history[a])<5 or h not in last_date or a not in last_date:
                continue
            def score_stats(team):
                vals=np.asarray(history[team][-10:],float)
                return np.mean(vals,axis=0)
            hp,ap=score_stats(h),score_stats(a)
            hr=max(0,(current-last_date[h]).days); ar=max(0,(current-last_date[a]).days)
            X.append([hp[0],hp[1],ap[0],ap[1],hp[0]-hp[1],ap[0]-ap[1],
                      hr,ar,hr-ar,float(hr<=6),float(ar<=6),float(hr>=13),float(ar>=13)])
            ym.append(g["hs"]-g["as"]); yt.append(g["hs"]+g["as"])
            dates.append(game_date); keys.append((game_date,str(g["id"]),g))
        for g in batch:
            history[g["home"]].append((g["hs"],g["as"]))
            history[g["away"]].append((g["as"],g["hs"]))
            last_date[g["home"]]=current; last_date[g["away"]]=current
    return np.asarray(X,float),np.asarray(ym,float),np.asarray(yt,float),names,dates,keys

def benchmark(report,games,keys,start,end,target):
    rows={(str(g["date"]),str(g["id"])):g for g in games}
    selected=[rows[(d,k)] for d,k,_ in keys if start<=int(d[:4])<=end and (d,k) in rows]
    model=np.asarray(report["holdout_predictions"],float)
    if len(model)!=len(selected):
        raise RuntimeError(f"SITUATIONAL_BENCHMARK_ALIGNMENT_FAILED:{target}:model={len(model)}:rows={len(selected)}")
    field="spread_line" if target=="margin" else "total_line"
    market=np.asarray([g.get(field) for g in selected],object)
    actual=np.asarray([g["hs"]-g["as"] if target=="margin" else g["hs"]+g["as"] for g in selected],float)
    valid=np.asarray([v is not None for v in market])
    market=market[valid].astype(float); actual=actual[valid]; model=model[valid]
    result={"n_holdout":int(valid.sum()),"rmse":float(np.sqrt(np.mean((market-actual)**2))),
            "source_field":field,"comparison":"MODEL_VS_CLOSING_LINE_REPORTED_ONLY",
            "paired_rmse_bootstrap":base.bootstrap_rmse_delta(model,market,actual)}
    if target=="margin":
        result["spread_line_home_margin_correlation"]=float(np.corrcoef(market,actual)[0,1])
    return result

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--seasons",default="2010,2011,2012,2013,2014,2015,2016,2017,2018,2019")
    ap.add_argument("--policy",default="config/nfl_research_search_policy_v1.json")
    ap.add_argument("--out",default="artifacts/football_baselines_attempt4.json")
    args=ap.parse_args()
    policy_path=Path(args.policy); policy=json.loads(policy_path.read_text())
    start,end=policy["immediate_holdout_range"]
    train_start,train_end=map(int,policy["training_seasons_for_immediate_holdout"].split("-"))
    seasons={int(s) for s in args.seasons.split(",") if s.strip()}
    required=set(range(train_start,end+1))
    if not required.issubset(seasons): raise RuntimeError(f"SEASONS_OMIT_POLICY_WINDOW:{sorted(required-seasons)}")
    games,game_sha,_=base.nfl(seasons)
    games=[g for g in games if g["date"][:4].isdigit() and int(g["date"][:4])<=end]
    X,ym,yt,names,dates,keys=situational_features(games)
    if len(X)<200: raise RuntimeError(f"SITUATIONAL_INSUFFICIENT_FEATURE_ROWS:{len(X)}")
    base.feature_names,base.hold_dates=names,dates
    targets={"margin":base.run_target(X,ym,start,end,close_threshold=7),
             "total":base.run_target(X,yt,start,end)}
    X0,ym0,yt0,names0,dates0=base.features(games,"baseline")
    base.feature_names,base.hold_dates=names0,dates0
    control={"budget_counted":False,"reason":"pre_registered_control_calibration",
             "targets":{"margin":base.run_target(X0,ym0,start,end,close_threshold=7),
                        "total":base.run_target(X0,yt0,start,end)}}
    report={"schema":"NFL_SITUATIONAL_ATTEMPT4_V1","source":"nflverse games.csv",
            "source_sha256":game_sha,"policy_path":str(policy_path),
            "policy_sha256":hashlib.sha256(policy_path.read_bytes()).hexdigest(),
            "training_years":[train_start,train_end],"holdout_years":[start,end],
            "feature_set":"situational_rest_flags_plus_baseline","feature_names":names,
            "games_fetched":len(games),"usable_rows":len(X),
            "status":"RESEARCH_ONLY_NOT_MODEL_P","targets":targets,
            "control_baseline_same_holdout":control,
            "closing_line_benchmark":{
                "margin":benchmark(targets["margin"],games,keys,start,end,"margin"),
                "total":benchmark(targets["total"],games,keys,start,end,"total")}}
    out=Path(args.out); out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,indent=2)+"\n"); print(json.dumps(report,indent=2))
if __name__=="__main__": main()
