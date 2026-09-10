#!/usr/bin/env python3
"""Fit dependency-light NFL and CFB research baselines from free result feeds.

This is deliberately separate from production engines: no odds, no credentials,
no eligibility or Model_P promotion.  Features are prior-game rolling scores;
same-date games are emitted before their results are appended.
"""
from __future__ import annotations
import argparse, csv, hashlib, io, json, sys
from datetime import date, timedelta
from collections import defaultdict
from itertools import groupby
from pathlib import Path
from urllib.request import Request, urlopen
import numpy as np

NFL_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
CFB_URL = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
ALPHAS = (0.1, 1.0, 10.0, 100.0, 300.0)

def get(url):
    try:
        with urlopen(Request(url, headers={"Accept":"application/json", "User-Agent":"SportsEdge-research-fit/1.0"}), timeout=90) as r:
            return r.read()
    except Exception as exc:
        raise RuntimeError(f"SOURCE_FETCH_FAILED:{url}:{type(exc).__name__}:{exc}") from exc

def nfl(seasons):
    raw = get(NFL_URL); rows=[]
    for r in csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))):
        try: season=int(r["season"]); hs=int(float(r["home_score"])); aas=int(float(r["away_score"]))
        except (KeyError,TypeError,ValueError): continue
        if season in seasons and r.get("game_type","REG") in ("REG","POST"):
            rows.append({"date":r.get("gameday") or f"{season}-01-01","id":r.get("game_id",""),"home":r["home_team"],"away":r["away_team"],"hs":hs,"as":aas})
    return rows, hashlib.sha256(raw).hexdigest(), NFL_URL

def cfb(seasons):
    rows=[]; blobs=[]
    for season in seasons:
        # A bare season (for example dates=2025) is rejected by ESPN. Query
        # weekly date ranges instead; groups=80 keeps this to the FBS feed.
        cursor=date(season, 8, 15)
        end=date(season + 1, 1, 20)
        while cursor <= end:
            week_end=min(cursor + timedelta(days=6), end)
            start=cursor.strftime("%Y%m%d"); finish=week_end.strftime("%Y%m%d")
            raw=get(f"{CFB_URL}?dates={start}-{finish}&limit=1000&groups=80"); blobs.append(raw)
            data=json.loads(raw)
            for e in data.get("events",[]):
                comp=(e.get("competitions") or [{}])[0]; teams=comp.get("competitors") or []
                if len(teams)!=2 or e.get("status",{}).get("type",{}).get("completed") is not True: continue
                home=next((x for x in teams if x.get("homeAway")=="home"),None); away=next((x for x in teams if x.get("homeAway")=="away"),None)
                if not home or not away: continue
                try: hs=int(home["score"]); aas=int(away["score"])
                except (KeyError,TypeError,ValueError): continue
                rows.append({"date":e.get("date","")[:10],"id":e.get("id",""),"home":home["team"]["id"],"away":away["team"]["id"],"hs":hs,"as":aas})
            cursor=week_end + timedelta(days=1)
    return rows, hashlib.sha256(b"".join(blobs)).hexdigest(), CFB_URL

def features(games):
    games=sorted(games,key=lambda x:(x["date"],x["id"])); hist=defaultdict(list); X=[]; ym=[]; yt=[]; dates=[]
    names=["home_points_for","home_points_against","away_points_for","away_points_against","home_net","away_net"]
    for date, grp in groupby(games,key=lambda x:x["date"]):
        batch=list(grp)
        for g in batch:
            h,a=g["home"],g["away"]
            if len(hist[h])>=5 and len(hist[a])>=5:
                mh=np.mean(hist[h][-10:],axis=0); ma=np.mean(hist[a][-10:],axis=0)
                X.append([mh[0],mh[1],ma[0],ma[1],mh[0]-mh[1],ma[0]-ma[1]])
                ym.append(g["hs"]-g["as"]); yt.append(g["hs"]+g["as"]); dates.append(date)
        for g in batch:
            hist[g["home"]].append((g["hs"],g["as"])); hist[g["away"]].append((g["as"],g["hs"]))
    return np.asarray(X,float),np.asarray(ym,float),np.asarray(yt,float),names,dates

def scale(a,b):
    mu=a.mean(0); sd=a.std(0); sd[sd==0]=1; return (a-mu)/sd,(b-mu)/sd
def fit(x,y,alpha):
    xc=x-x.mean(0); yc=y-y.mean(); beta=np.linalg.solve(xc.T@xc+alpha*np.eye(x.shape[1]),xc.T@yc)
    return beta,float(y.mean()-x.mean(0)@beta)
def score(xtr,ytr,xte,yte,alpha):
    a,b=scale(xtr,xte); beta,i=fit(a,ytr,alpha); pred=b@beta+i; mse=np.mean((pred-yte)**2); base=np.mean((ytr.mean()-yte)**2)
    return {"rmse":float(np.sqrt(mse)),"baseline_rmse":float(np.sqrt(base)),"r2_vs_mean":float(1-mse/base) if base else 0.0,"mae":float(np.mean(abs(pred-yte)))}
def run_target(x,y,hold):
    mask=np.array([d.startswith(str(hold)) for d in hold_dates]); tr=x[~mask]; yt=y[~mask]; te=x[mask]; ye=y[mask]
    if len(tr)<100 or len(te)<20: raise RuntimeError("INSUFFICIENT_DATE_SPLIT")
    ms={a:[] for a in ALPHAS}; n=len(tr)
    for k in range(1,5):
        cut=max(20,int(n*k/5)); end=max(cut+1,int(n*(k+1)/5)); a,b=scale(tr[:cut],tr[cut:end])
        for alpha in ALPHAS: ms[alpha].append(float(np.mean((b@fit(a,yt[:cut],alpha)[0]+fit(a,yt[:cut],alpha)[1]-yt[cut:end])**2)))
    alpha=min(ms,key=lambda z:np.mean(ms[z])); rng=np.random.default_rng(0); shuffled=yt.copy(); rng.shuffle(shuffled)
    placebo=score(tr,shuffled,te,ye,alpha); real=score(tr,yt,te,ye,alpha); a,_=scale(tr,tr); beta,_=fit(a,yt,alpha)
    return {"cv_selected_alpha":alpha,"cv_grid_mse":{str(k):float(np.mean(v)) for k,v in ms.items()},"placebo":placebo,"holdout":real,"coefficients":dict(zip(feature_names,map(float,beta))),"signal_verdict":"NO_SIGNAL" if real["r2_vs_mean"]<=0 else "WEAK_SIGNAL" if real["r2_vs_mean"]<.03 else "LEAKAGE_SUSPECTED" if placebo["r2_vs_mean"]>.05 else "SIGNAL_PRESENT"}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--seasons",default="2021,2022,2023,2024,2025"); ap.add_argument("--holdout",type=int,default=2025); ap.add_argument("--out",default="artifacts/football_baselines.json"); args=ap.parse_args()
    seasons={int(x) for x in args.seasons.split(",")}; reports={}
    for sport,loader in (("NFL",nfl),("CFB",cfb)):
        games,sha,source=loader(seasons)
        if not games: raise RuntimeError(f"{sport}: NO_COMPLETED_GAMES")
        global hold_dates,feature_names
        X,ym,yt,feature_names,hold_dates=features(games)
        reports[sport]={"source":source,"source_sha256":sha,"games_fetched":len(games),"usable_rows":len(X),"status":"RESEARCH_ONLY_NOT_MODEL_P","targets":{"margin":run_target(X,ym,args.holdout),"total":run_target(X,yt,args.holdout)}}
    out=Path(args.out); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps({"schema":"FOOTBALL_BASELINES_V1","reports":reports},indent=2)+"\n"); print(json.dumps(reports,indent=2)); return 0
if __name__=="__main__": raise SystemExit(main())

