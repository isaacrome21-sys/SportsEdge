#!/usr/bin/env python3
"""NFL Attempt 9: point-in-time exponentially recency-weighted baseline."""
from __future__ import annotations
import argparse,hashlib,json
from collections import defaultdict
from itertools import groupby
from pathlib import Path
import numpy as np
import fit_football_baselines as base
DECAY=0.85
def weighted(v):
    a=np.asarray(v[-10:],float);w=DECAY**np.arange(len(a)-1,-1,-1);return np.average(a,axis=0,weights=w)
def features(games):
    ordered=sorted(games,key=lambda g:(g["date"],g["id"]));hist=defaultdict(list);X=[];ym=[];yt=[];dates=[];keys=[]
    names=["home_points_for","home_points_against","away_points_for","away_points_against","home_net","away_net"]
    for d,grp in groupby(ordered,key=lambda g:g["date"]):
        batch=list(grp)
        for g in batch:
            h,a=g["home"],g["away"]
            if len(hist[h])<5 or len(hist[a])<5:continue
            hp,ap=weighted(hist[h]),weighted(hist[a])
            X.append([hp[0],hp[1],ap[0],ap[1],hp[0]-hp[1],ap[0]-ap[1]]);ym.append(g["hs"]-g["as"]);yt.append(g["hs"]+g["as"]);dates.append(d);keys.append((d,str(g["id"]),g))
        for g in batch:
            hist[g["home"]].append((g["hs"],g["as"]));hist[g["away"]].append((g["as"],g["hs"]))
    return np.asarray(X,float),np.asarray(ym,float),np.asarray(yt,float),names,dates,keys
def bench(rep,games,keys,start,end,target):
    rows={(str(g["date"]),str(g["id"])):g for g in games};sel=[rows[(d,k)] for d,k,_ in keys if start<=int(d[:4])<=end and (d,k) in rows];pred=np.asarray(rep["holdout_predictions"],float)
    if len(pred)!=len(sel):raise RuntimeError(f"RECENCY_ALIGNMENT_FAILED:{target}:{len(pred)}:{len(sel)}")
    field="spread_line" if target=="margin" else "total_line";m=np.asarray([g.get(field) for g in sel],object);y=np.asarray([g["hs"]-g["as"] if target=="margin" else g["hs"]+g["as"] for g in sel],float);v=np.asarray([x is not None for x in m]);m=m[v].astype(float);y=y[v];pred=pred[v]
    r={"n_holdout":int(v.sum()),"rmse":float(np.sqrt(np.mean((m-y)**2))),"source_field":field,"comparison":"MODEL_VS_CLOSING_LINE_REPORTED_ONLY","paired_rmse_bootstrap":base.bootstrap_rmse_delta(pred,m,y)}
    if target=="margin":r["spread_line_home_margin_correlation"]=float(np.corrcoef(m,y)[0,1])
    return r
def main():
    ap=argparse.ArgumentParser();ap.add_argument("--seasons",default="2010,2011,2012,2013,2014,2015,2016,2017,2018,2019");ap.add_argument("--policy",default="config/nfl_research_search_policy_v1.json");ap.add_argument("--out",default="artifacts/football_baselines_attempt9.json");a=ap.parse_args()
    pp=Path(a.policy);p=json.loads(pp.read_text());start,end=p["immediate_holdout_range"];ts,te=map(int,p["training_seasons_for_immediate_holdout"].split("-"));seasons={int(x) for x in a.seasons.split(",") if x.strip()}
    if not set(range(ts,end+1)).issubset(seasons):raise RuntimeError("SEASONS_OMIT_POLICY_WINDOW")
    games,gsha,_=base.nfl(seasons);games=[g for g in games if g["date"][:4].isdigit() and int(g["date"][:4])<=end];X,ym,yt,names,dates,keys=features(games)
    if len(X)<200:raise RuntimeError(f"RECENCY_INSUFFICIENT_FEATURE_ROWS:{len(X)}")
    base.feature_names,base.hold_dates=names,dates;targets={"margin":base.run_target(X,ym,start,end,close_threshold=7),"total":base.run_target(X,yt,start,end)}
    X0,y0,t0,n0,d0=base.features(games,"baseline");base.feature_names,base.hold_dates=n0,d0;control={"budget_counted":False,"reason":"pre_registered_control_calibration","targets":{"margin":base.run_target(X0,y0,start,end,close_threshold=7),"total":base.run_target(X0,t0,start,end)}}
    report={"schema":"NFL_RECENCY_ATTEMPT9_V1","source":"nflverse games.csv","source_sha256":gsha,"policy_path":str(pp),"policy_sha256":hashlib.sha256(pp.read_bytes()).hexdigest(),"training_years":[ts,te],"holdout_years":[start,end],"feature_set":"exponential_recency_weighted_baseline","decay":DECAY,"feature_names":names,"games_fetched":len(games),"usable_rows":len(X),"status":"RESEARCH_ONLY_NOT_MODEL_P","targets":targets,"control_baseline_same_holdout":control,"closing_line_benchmark":{"margin":bench(targets["margin"],games,keys,start,end,"margin"),"total":bench(targets["total"],games,keys,start,end,"total")}}
    out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,indent=2)+"\n");print(json.dumps(report,indent=2))
if __name__=="__main__":main()
