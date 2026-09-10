#!/usr/bin/env python3
"""NFL Attempt 6: pregame weather and venue features."""
from __future__ import annotations
import argparse,csv,hashlib,io,json
from collections import defaultdict
from itertools import groupby
from pathlib import Path
from urllib.request import Request,urlopen
import numpy as np
import fit_football_baselines as base

URL="https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
def raw():
    with urlopen(Request(URL,headers={"User-Agent":"SportsEdge-research-fit/1.0"}),timeout=120) as r:return r.read()
def wx_map(blob):
    out={}
    for r in csv.DictReader(io.StringIO(blob.decode("utf-8-sig"))):
        try:
            temp=float(r["temp"]) if r.get("temp") not in ("",None) else 70.0
            wind=float(r["wind"]) if r.get("wind") not in ("",None) else 0.0
        except (TypeError,ValueError): continue
        roof=(r.get("roof") or "").lower(); surface=(r.get("surface") or "").lower()
        out[str(r.get("game_id",""))]=[temp,wind,float(roof in ("dome","closed","retractable roof")),float(surface=="fieldturf")]
    return out
def features(games,wx):
    ordered=sorted(games,key=lambda g:(g["date"],g["id"]));hist=defaultdict(list);X=[];ym=[];yt=[];dates=[];keys=[]
    names=["home_points_for","home_points_against","away_points_for","away_points_against","home_net","away_net","temperature","wind","dome","fieldturf"]
    for d,grp in groupby(ordered,key=lambda g:g["date"]):
        batch=list(grp)
        for g in batch:
            h,a=g["home"],g["away"];w=wx.get(str(g["id"]))
            if len(hist[h])<5 or len(hist[a])<5 or w is None:continue
            hp=np.mean(np.asarray(hist[h][-10:],float),axis=0);ap=np.mean(np.asarray(hist[a][-10:],float),axis=0)
            X.append([hp[0],hp[1],ap[0],ap[1],hp[0]-hp[1],ap[0]-ap[1],w[0],w[1],w[2],w[3]])
            ym.append(g["hs"]-g["as"]);yt.append(g["hs"]+g["as"]);dates.append(d);keys.append((d,str(g["id"]),g))
        for g in batch:
            hist[g["home"]].append((g["hs"],g["as"]));hist[g["away"]].append((g["as"],g["hs"]))
    return np.asarray(X,float),np.asarray(ym,float),np.asarray(yt,float),names,dates,keys
def bench(report,games,keys,start,end,target):
    rows={(str(g["date"]),str(g["id"])):g for g in games};sel=[rows[(d,k)] for d,k,_ in keys if start<=int(d[:4])<=end and (d,k) in rows];pred=np.asarray(report["holdout_predictions"],float)
    if len(pred)!=len(sel):raise RuntimeError(f"WEATHER_ALIGNMENT_FAILED:{target}:{len(pred)}:{len(sel)}")
    field="spread_line" if target=="margin" else "total_line";market=np.asarray([g.get(field) for g in sel],object);actual=np.asarray([g["hs"]-g["as"] if target=="margin" else g["hs"]+g["as"] for g in sel],float);v=np.asarray([x is not None for x in market]);market=market[v].astype(float);actual=actual[v];pred=pred[v]
    r={"n_holdout":int(v.sum()),"rmse":float(np.sqrt(np.mean((market-actual)**2))),"source_field":field,"comparison":"MODEL_VS_CLOSING_LINE_REPORTED_ONLY","paired_rmse_bootstrap":base.bootstrap_rmse_delta(pred,market,actual)}
    if target=="margin":r["spread_line_home_margin_correlation"]=float(np.corrcoef(market,actual)[0,1])
    return r
def main():
    ap=argparse.ArgumentParser();ap.add_argument("--seasons",default="2010,2011,2012,2013,2014,2015,2016,2017,2018,2019");ap.add_argument("--policy",default="config/nfl_research_search_policy_v1.json");ap.add_argument("--out",default="artifacts/football_baselines_attempt6.json");a=ap.parse_args()
    pp=Path(a.policy);p=json.loads(pp.read_text());start,end=p["immediate_holdout_range"];ts,te=map(int,p["training_seasons_for_immediate_holdout"].split("-"));seasons={int(x) for x in a.seasons.split(",") if x.strip()}
    if not set(range(ts,end+1)).issubset(seasons):raise RuntimeError("SEASONS_OMIT_POLICY_WINDOW")
    games,gsha,_=base.nfl(seasons);games=[g for g in games if g["date"][:4].isdigit() and int(g["date"][:4])<=end];blob=raw();wx=wx_map(blob);X,ym,yt,names,dates,keys=features(games,wx)
    if len(X)<200:raise RuntimeError(f"WEATHER_INSUFFICIENT_FEATURE_ROWS:{len(X)}")
    base.feature_names,base.hold_dates=names,dates;targets={"margin":base.run_target(X,ym,start,end,close_threshold=7),"total":base.run_target(X,yt,start,end)}
    X0,y0,t0,n0,d0=base.features(games,"baseline");base.feature_names,base.hold_dates=n0,d0;control={"budget_counted":False,"reason":"pre_registered_control_calibration","targets":{"margin":base.run_target(X0,y0,start,end,close_threshold=7),"total":base.run_target(X0,t0,start,end)}}
    report={"schema":"NFL_WEATHER_VENUE_ATTEMPT6_V1","source":URL,"games_source_sha256":gsha,"weather_source_sha256":hashlib.sha256(blob).hexdigest(),"policy_path":str(pp),"policy_sha256":hashlib.sha256(pp.read_bytes()).hexdigest(),"training_years":[ts,te],"holdout_years":[start,end],"feature_set":"weather_venue_plus_baseline","feature_names":names,"games_fetched":len(games),"usable_rows":len(X),"status":"RESEARCH_ONLY_NOT_MODEL_P","targets":targets,"control_baseline_same_holdout":control,"closing_line_benchmark":{"margin":bench(targets["margin"],games,keys,start,end,"margin"),"total":bench(targets["total"],games,keys,start,end,"total")}}
    out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,indent=2)+"\n");print(json.dumps(report,indent=2))
if __name__=="__main__":main()
