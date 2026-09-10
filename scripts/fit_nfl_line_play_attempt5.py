#!/usr/bin/env python3
"""NFL Attempt 5: point-in-time line-play efficiency."""
from __future__ import annotations
import argparse, hashlib, io, json
from collections import defaultdict
from itertools import groupby
from pathlib import Path
from urllib.request import Request,urlopen
import numpy as np
import pandas as pd
import fit_football_baselines as base

URL="https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{season}.parquet"
def fetch(url):
    with urlopen(Request(url,headers={"User-Agent":"SportsEdge-research-fit/1.0"}),timeout=180) as r:return r.read()
def pbp_stats(seasons):
    out={}; blobs=[]
    for s in sorted(seasons):
        raw=fetch(URL.format(season=s)); blobs.append(raw)
        f=pd.read_parquet(io.BytesIO(raw),columns=["game_id","posteam","defteam","play_type","season_type","pass","sack","qb_hit"])
        f=f[f["season_type"].isin(["REG","POST"]) & f["posteam"].notna() & f["defteam"].notna()]
        f=f[f["play_type"].isin(["pass","run","qb_kneel","qb_spike"])]
        if f.empty: continue
        for (gid,off,defn),g in f.groupby(["game_id","posteam","defteam"],sort=False):
            passes=float(g["pass"].eq(1).sum())
            out[(str(gid),str(off))]={"pressure":float(g["qb_hit"].fillna(0).eq(1).sum())/max(1,passes),
                "sack":float(g["sack"].fillna(0).eq(1).sum())/max(1,passes),"defteam":str(defn)}
    return out,hashlib.sha256(b"".join(blobs)).hexdigest()
def features(games,stats):
    ordered=sorted(games,key=lambda g:(g["date"],g["id"])); hist=defaultdict(list); X=[];ym=[];yt=[];dates=[];keys=[]
    names=["home_points_for","home_points_against","away_points_for","away_points_against","home_net","away_net",
           "home_pressure_rate","home_sack_rate","home_def_pressure_rate","home_def_sack_rate",
           "away_pressure_rate","away_sack_rate","away_def_pressure_rate","away_def_sack_rate"]
    for d,grp in groupby(ordered,key=lambda g:g["date"]):
        batch=list(grp)
        for g in batch:
            h,a=g["home"],g["away"]; hs=stats.get((str(g["id"]),str(h))); aas=stats.get((str(g["id"]),str(a)))
            if len(hist[h])<5 or len(hist[a])<5 or not hs or not aas: continue
            hp=np.mean(np.asarray(hist[h][-10:],float),axis=0); ap=np.mean(np.asarray(hist[a][-10:],float),axis=0)
            X.append([hp[0],hp[1],ap[0],ap[1],hp[0]-hp[1],ap[0]-ap[1],hp[2],hp[3],ap[2],ap[3],ap[2],ap[3],hp[2],hp[3]])
            ym.append(g["hs"]-g["as"]);yt.append(g["hs"]+g["as"]);dates.append(d);keys.append((d,str(g["id"]),g))
        for g in batch:
            h,a=g["home"],g["away"]; hs=stats.get((str(g["id"]),str(h))); aas=stats.get((str(g["id"]),str(a)))
            if hs and aas:
                hist[h].append([g["hs"],g["as"],hs["pressure"],hs["sack"]])
                hist[a].append([g["as"],g["hs"],aas["pressure"],aas["sack"]])
    return np.asarray(X,float),np.asarray(ym,float),np.asarray(yt,float),names,dates,keys
def bench(report,games,keys,start,end,target):
    rows={(str(g["date"]),str(g["id"])):g for g in games}
    sel=[rows[(d,k)] for d,k,_ in keys if start<=int(d[:4])<=end and (d,k) in rows]
    pred=np.asarray(report["holdout_predictions"],float)
    if len(pred)!=len(sel): raise RuntimeError(f"LINE_PLAY_ALIGNMENT_FAILED:{target}:{len(pred)}:{len(sel)}")
    field="spread_line" if target=="margin" else "total_line"; market=np.asarray([g.get(field) for g in sel],object)
    actual=np.asarray([g["hs"]-g["as"] if target=="margin" else g["hs"]+g["as"] for g in sel],float)
    valid=np.asarray([v is not None for v in market]); market=market[valid].astype(float);actual=actual[valid];pred=pred[valid]
    r={"n_holdout":int(valid.sum()),"rmse":float(np.sqrt(np.mean((market-actual)**2))),"source_field":field,
       "comparison":"MODEL_VS_CLOSING_LINE_REPORTED_ONLY","paired_rmse_bootstrap":base.bootstrap_rmse_delta(pred,market,actual)}
    if target=="margin": r["spread_line_home_margin_correlation"]=float(np.corrcoef(market,actual)[0,1])
    return r
def main():
    ap=argparse.ArgumentParser();ap.add_argument("--seasons",default="2010,2011,2012,2013,2014,2015,2016,2017,2018,2019");ap.add_argument("--policy",default="config/nfl_research_search_policy_v1.json");ap.add_argument("--out",default="artifacts/football_baselines_attempt5.json");a=ap.parse_args()
    pp=Path(a.policy);p=json.loads(pp.read_text());start,end=p["immediate_holdout_range"]; ts,te=map(int,p["training_seasons_for_immediate_holdout"].split("-")); seasons={int(x) for x in a.seasons.split(",") if x.strip()}
    if not set(range(ts,end+1)).issubset(seasons): raise RuntimeError("SEASONS_OMIT_POLICY_WINDOW")
    games,gsha,_=base.nfl(seasons);games=[g for g in games if g["date"][:4].isdigit() and int(g["date"][:4])<=end]
    st,ss=pbp_stats(seasons);X,ym,yt,names,dates,keys=features(games,st)
    if len(X)<200: raise RuntimeError(f"LINE_PLAY_INSUFFICIENT_FEATURE_ROWS:{len(X)}")
    base.feature_names,base.hold_dates=names,dates; targets={"margin":base.run_target(X,ym,start,end,close_threshold=7),"total":base.run_target(X,yt,start,end)}
    X0,y0,t0,n0,d0=base.features(games,"baseline");base.feature_names,base.hold_dates=n0,d0
    control={"budget_counted":False,"reason":"pre_registered_control_calibration","targets":{"margin":base.run_target(X0,y0,start,end,close_threshold=7),"total":base.run_target(X0,t0,start,end)}}
    report={"schema":"NFL_LINE_PLAY_ATTEMPT5_V1","source":URL,"games_source_sha256":gsha,"pbp_source_sha256":ss,"policy_path":str(pp),"policy_sha256":hashlib.sha256(pp.read_bytes()).hexdigest(),"training_years":[ts,te],"holdout_years":[start,end],"feature_set":"line_play_pressure_sack_plus_baseline","feature_names":names,"games_fetched":len(games),"usable_rows":len(X),"status":"RESEARCH_ONLY_NOT_MODEL_P","targets":targets,"control_baseline_same_holdout":control,"closing_line_benchmark":{"margin":bench(targets["margin"],games,keys,start,end,"margin"),"total":bench(targets["total"],games,keys,start,end,"total")}}
    out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,indent=2)+"\n");print(json.dumps(report,indent=2))
if __name__=="__main__":main()
