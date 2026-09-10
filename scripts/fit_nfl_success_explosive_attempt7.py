#!/usr/bin/env python3
"""NFL Attempt 7: point-in-time success and explosive-play rates."""
from __future__ import annotations
import argparse,hashlib,io,json
from collections import defaultdict
from itertools import groupby
from pathlib import Path
from urllib.request import Request,urlopen
import numpy as np
import pandas as pd
import fit_football_baselines as base
URL="https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{season}.parquet"
def fetch(u):
    with urlopen(Request(u,headers={"User-Agent":"SportsEdge-research-fit/1.0"}),timeout=180) as r:return r.read()
def stats(seasons):
    out={}; blobs=[]
    for s in sorted(seasons):
        raw=fetch(URL.format(season=s));blobs.append(raw)
        f=pd.read_parquet(io.BytesIO(raw),columns=["game_id","posteam","defteam","play_type","season_type","first_down","yards_gained"])
        f=f[f["season_type"].isin(["REG","POST"])&f["posteam"].notna()&f["defteam"].notna()&f["play_type"].isin(["pass","run","qb_kneel","qb_spike"])]
        for (gid,off,defn),g in f.groupby(["game_id","posteam","defteam"],sort=False):
            n=len(g);success=float(g["first_down"].fillna(0).eq(1).sum())/max(1,n)
            explosive=float(((g["play_type"].eq("pass")&g["yards_gained"].ge(20))|(g["play_type"].eq("run")&g["yards_gained"].ge(10))).sum())/max(1,n)
            out[(str(gid),str(off))]={"success":success,"explosive":explosive,"defteam":str(defn)}
    return out,hashlib.sha256(b"".join(blobs)).hexdigest()
def features(games,st):
    ordered=sorted(games,key=lambda g:(g["date"],g["id"]));hist=defaultdict(list);X=[];ym=[];yt=[];dates=[];keys=[]
    names=["home_points_for","home_points_against","away_points_for","away_points_against","home_net","away_net","home_success_rate","home_explosive_rate","home_def_success_rate","home_def_explosive_rate","away_success_rate","away_explosive_rate","away_def_success_rate","away_def_explosive_rate"]
    for d,grp in groupby(ordered,key=lambda g:g["date"]):
        batch=list(grp)
        for g in batch:
            h,a=g["home"],g["away"];hs=st.get((str(g["id"]),str(h)));aa=st.get((str(g["id"]),str(a)))
            if len(hist[h])<5 or len(hist[a])<5 or not hs or not aa:continue
            hp=np.mean(np.asarray(hist[h][-10:],float),axis=0);ap=np.mean(np.asarray(hist[a][-10:],float),axis=0)
            X.append([hp[0],hp[1],ap[0],ap[1],hp[0]-hp[1],ap[0]-ap[1],hp[2],hp[3],hp[4],hp[5],ap[2],ap[3],ap[4],ap[5]])
            ym.append(g["hs"]-g["as"]);yt.append(g["hs"]+g["as"]);dates.append(d);keys.append((d,str(g["id"]),g))
        for g in batch:
            h,a=g["home"],g["away"];hs=st.get((str(g["id"]),str(h)));aa=st.get((str(g["id"]),str(a)))
            if hs and aa:
                hist[h].append([g["hs"],g["as"],hs["success"],hs["explosive"],aa["success"],aa["explosive"]])
                hist[a].append([g["as"],g["hs"],aa["success"],aa["explosive"],hs["success"],hs["explosive"]])
    return np.asarray(X,float),np.asarray(ym,float),np.asarray(yt,float),names,dates,keys
def bench(rep,games,keys,start,end,target):
    rows={(str(g["date"]),str(g["id"])):g for g in games};sel=[rows[(d,k)] for d,k,_ in keys if start<=int(d[:4])<=end and (d,k) in rows];pred=np.asarray(rep["holdout_predictions"],float)
    if len(pred)!=len(sel):raise RuntimeError(f"SUCCESS_RATE_ALIGNMENT_FAILED:{target}:{len(pred)}:{len(sel)}")
    field="spread_line" if target=="margin" else "total_line";m=np.asarray([g.get(field) for g in sel],object);y=np.asarray([g["hs"]-g["as"] if target=="margin" else g["hs"]+g["as"] for g in sel],float);v=np.asarray([x is not None for x in m]);m=m[v].astype(float);y=y[v];pred=pred[v]
    r={"n_holdout":int(v.sum()),"rmse":float(np.sqrt(np.mean((m-y)**2))),"source_field":field,"comparison":"MODEL_VS_CLOSING_LINE_REPORTED_ONLY","paired_rmse_bootstrap":base.bootstrap_rmse_delta(pred,m,y)}
    if target=="margin":r["spread_line_home_margin_correlation"]=float(np.corrcoef(m,y)[0,1])
    return r
def main():
    ap=argparse.ArgumentParser();ap.add_argument("--seasons",default="2010,2011,2012,2013,2014,2015,2016,2017,2018,2019");ap.add_argument("--policy",default="config/nfl_research_search_policy_v1.json");ap.add_argument("--out",default="artifacts/football_baselines_attempt7.json");a=ap.parse_args()
    pp=Path(a.policy);p=json.loads(pp.read_text());start,end=p["immediate_holdout_range"];ts,te=map(int,p["training_seasons_for_immediate_holdout"].split("-"));seasons={int(x) for x in a.seasons.split(",") if x.strip()}
    if not set(range(ts,end+1)).issubset(seasons):raise RuntimeError("SEASONS_OMIT_POLICY_WINDOW")
    games,gsha,_=base.nfl(seasons);games=[g for g in games if g["date"][:4].isdigit() and int(g["date"][:4])<=end];st,ss=stats(seasons);X,ym,yt,names,dates,keys=features(games,st)
    if len(X)<200:raise RuntimeError(f"SUCCESS_RATE_INSUFFICIENT_FEATURE_ROWS:{len(X)}")
    base.feature_names,base.hold_dates=names,dates;targets={"margin":base.run_target(X,ym,start,end,close_threshold=7),"total":base.run_target(X,yt,start,end)}
    X0,y0,t0,n0,d0=base.features(games,"baseline");base.feature_names,base.hold_dates=n0,d0;control={"budget_counted":False,"reason":"pre_registered_control_calibration","targets":{"margin":base.run_target(X0,y0,start,end,close_threshold=7),"total":base.run_target(X0,t0,start,end)}}
    report={"schema":"NFL_SUCCESS_EXPLOSIVE_ATTEMPT7_V1","source":URL,"games_source_sha256":gsha,"pbp_source_sha256":ss,"policy_path":str(pp),"policy_sha256":hashlib.sha256(pp.read_bytes()).hexdigest(),"training_years":[ts,te],"holdout_years":[start,end],"feature_set":"success_explosive_plus_baseline","feature_names":names,"games_fetched":len(games),"usable_rows":len(X),"status":"RESEARCH_ONLY_NOT_MODEL_P","targets":targets,"control_baseline_same_holdout":control,"closing_line_benchmark":{"margin":bench(targets["margin"],games,keys,start,end,"margin"),"total":bench(targets["total"],games,keys,start,end,"total")}}
    out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,indent=2)+"\n");print(json.dumps(report,indent=2))
if __name__=="__main__":main()
