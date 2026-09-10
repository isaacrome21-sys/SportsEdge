#!/usr/bin/env python3
"""Fit dependency-light NFL and CFB research baselines from free result feeds.

This is deliberately separate from production engines: no odds, no credentials,
no eligibility or Model_P promotion.  Features are prior-game rolling scores;
same-date games are emitted before their results are appended.
"""
from __future__ import annotations
import argparse, csv, hashlib, io, json, re, sys
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
            def optional_float(key):
                try: return float(r[key]) if r.get(key) not in (None, "") else None
                except (TypeError, ValueError): return None
            rows.append({"date":r.get("gameday") or f"{season}-01-01","id":r.get("game_id",""),"home":r["home_team"],"away":r["away_team"],"hs":hs,"as":aas,"spread_line":optional_float("spread_line"),"total_line":optional_float("total_line"),"home_qb_id":(r.get("home_qb_id") or r.get("home_qb_name") or "").strip(),"away_qb_id":(r.get("away_qb_id") or r.get("away_qb_name") or "").strip()})
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

def features(games, feature_set="baseline"):
    games=sorted(games,key=lambda x:(x["date"],x["id"])); hist=defaultdict(list); qbhist=defaultdict(list); X=[]; ym=[]; yt=[]; dates=[]
    names=["home_points_for","home_points_against","away_points_for","away_points_against","home_net","away_net"]
    if feature_set == "opponent_strength": names += ["home_opponent_strength","away_opponent_strength"]
    if feature_set == "quarterback": names += ["home_qb_prior_margin","away_qb_prior_margin","home_qb_prior_total","away_qb_prior_total","home_qb_prior_starts","away_qb_prior_starts"]
    for date, grp in groupby(games,key=lambda x:x["date"]):
        batch=list(grp)
        for g in batch:
            h,a=g["home"],g["away"]
            if len(hist[h])>=5 and len(hist[a])>=5:
                mh=np.mean([x[:2] for x in hist[h][-10:]],axis=0); ma=np.mean([x[:2] for x in hist[a][-10:]],axis=0)
                row=[mh[0],mh[1],ma[0],ma[1],mh[0]-mh[1],ma[0]-ma[1]]
                if feature_set == "quarterback":
                    hq,aq=g.get("home_qb_id"),g.get("away_qb_id")
                    if not hq or not aq: continue
                    def qb_stats(qb):
                        prior=qbhist[qb][-10:]
                        if not prior: return (0.0,0.0,0.0)
                        return (float(np.mean([v[0] for v in prior])),float(np.mean([v[1] for v in prior])),float(len(prior)))
                    hqs,aqs=qb_stats(hq),qb_stats(aq)
                    row += [hqs[0],aqs[0],hqs[1],aqs[1],hqs[2],aqs[2]]
                if feature_set == "opponent_strength":
                    def strength(team):
                        vals=[np.mean([x[:2] for x in hist[opp][-10:]],axis=0)[0]-np.mean([x[:2] for x in hist[opp][-10:]],axis=0)[1] for _,_,opp in hist[team] if hist[opp]]
                        return float(np.mean(vals)) if vals else 0.0
                    row += [strength(h), strength(a)]
                X.append(row)
                ym.append(g["hs"]-g["as"]); yt.append(g["hs"]+g["as"]); dates.append(date)
        for g in batch:
            hist[g["home"]].append((g["hs"],g["as"],g["away"])); hist[g["away"]].append((g["as"],g["hs"],g["home"]))
            if feature_set == "quarterback" and g.get("home_qb_id") and g.get("away_qb_id"):
                qbhist[g["home_qb_id"]].append((g["hs"]-g["as"],g["hs"],g["hs"]+g["as"]))
                qbhist[g["away_qb_id"]].append((g["as"]-g["hs"],g["as"],g["hs"]+g["as"]))
    return np.asarray(X,float),np.asarray(ym,float),np.asarray(yt,float),names,dates

def scale(a,b):
    mu=a.mean(0); sd=a.std(0); sd[sd==0]=1; return (a-mu)/sd,(b-mu)/sd
def fit(x,y,alpha):
    xc=x-x.mean(0); yc=y-y.mean(); beta=np.linalg.solve(xc.T@xc+alpha*np.eye(x.shape[1]),xc.T@yc)
    return beta,float(y.mean()-x.mean(0)@beta)
def score(xtr,ytr,xte,yte,alpha):
    a,b=scale(xtr,xte); beta,i=fit(a,ytr,alpha); pred=b@beta+i; mse=np.mean((pred-yte)**2); base=np.mean((ytr.mean()-yte)**2)
    return {"rmse":float(np.sqrt(mse)),"baseline_rmse":float(np.sqrt(base)),"r2_vs_mean":float(1-mse/base) if base else 0.0,"mae":float(np.mean(abs(pred-yte)))}
def bootstrap_rmse_delta(model, market, actual, reps=2000):
    rng=np.random.default_rng(1); n=len(actual); deltas=[]
    for _ in range(reps):
        idx=rng.integers(0,n,n); y=actual[idx]
        deltas.append(float(np.sqrt(np.mean((model[idx]-y)**2))-np.sqrt(np.mean((market[idx]-y)**2))))
    sq_delta=(model-actual)**2-(market-actual)**2
    detectable=1.96*float(np.std(sq_delta,ddof=1))/(2*float(np.sqrt(np.mean((market-actual)**2)))*np.sqrt(n))
    return {"reps":reps,"delta_model_minus_market":float(np.sqrt(np.mean((model-actual)**2))-np.sqrt(np.mean((market-actual)**2))),"ci95_q025":float(np.quantile(deltas,.025)),"median":float(np.quantile(deltas,.50)),"ci95_q975":float(np.quantile(deltas,.975)),"approx_95pct_detectable_rmse_gap":detectable}
def cv_null(x,y,alpha,shuffles=200):
    """Training-only null; never evaluates the already-used holdout."""
    n=len(y); values=[]; rng=np.random.default_rng(0)
    for _ in range(shuffles):
        z=y.copy(); rng.shuffle(z); pred=[]; actual=[]; base=[]
        for k in range(1,5):
            cut=max(20,int(n*k/5)); end=max(cut+1,int(n*(k+1)/5)); a,b=scale(x[:cut],x[cut:end]); beta,i=fit(a,z[:cut],alpha)
            pred.extend(b@beta+i); actual.extend(y[cut:end]); base.extend([z[:cut].mean()]*(end-cut))
        mse=np.mean((np.asarray(pred)-actual)**2); bmse=np.mean((np.asarray(base)-actual)**2)
        values.append(float(1-mse/bmse) if bmse else 0.0)
    return {"n":shuffles,"q05":float(np.quantile(values,.05)),"q50":float(np.quantile(values,.50)),"q95":float(np.quantile(values,.95)),"max":float(max(values))}

def run_target(x,y,hold_start,hold_end,close_threshold=None):
    mask=np.array([hold_start <= int(d[:4]) <= hold_end for d in hold_dates]); tr=x[~mask]; yt=y[~mask]; te=x[mask]; ye=y[mask]
    if len(tr)<100 or len(te)<20: raise RuntimeError("INSUFFICIENT_DATE_SPLIT")
    ms={a:[] for a in ALPHAS}; n=len(tr)
    for k in range(1,5):
        cut=max(20,int(n*k/5)); end=max(cut+1,int(n*(k+1)/5)); a,b=scale(tr[:cut],tr[cut:end])
        for alpha in ALPHAS: ms[alpha].append(float(np.mean((b@fit(a,yt[:cut],alpha)[0]+fit(a,yt[:cut],alpha)[1]-yt[cut:end])**2)))
    alpha=min(ms,key=lambda z:np.mean(ms[z])); null=cv_null(tr,yt,alpha); rng=np.random.default_rng(0); shuffled=yt.copy(); rng.shuffle(shuffled)
    placebo=score(tr,shuffled,te,ye,alpha); real=score(tr,yt,te,ye,alpha); a,b=scale(tr,te); beta,i=fit(a,yt,alpha)
    holdout_pred=b@beta+i
    result={"cv_selected_alpha":alpha,"cv_grid_mse":{str(k):float(np.mean(v)) for k,v in ms.items()},"training_cv_placebo_null":null,"placebo":placebo,"holdout":real,"holdout_predictions":[float(v) for v in holdout_pred],"coefficients":dict(zip(feature_names,map(float,beta))),"signal_verdict":"NO_SIGNAL" if real["r2_vs_mean"]<=0 else "WEAK_SIGNAL" if real["r2_vs_mean"]<.03 else "LEAKAGE_SUSPECTED" if placebo["r2_vs_mean"]>.05 else "SIGNAL_PRESENT"}
    if close_threshold is not None:
        close=np.abs(ye)<=close_threshold
        result["close_game_split"]={"absolute_margin_threshold":close_threshold,"n":int(close.sum()),"metrics":score(tr,yt,te[close],ye[close],alpha) if close.any() else None}
    return result

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--seasons",default="2021,2022,2023,2024,2025"); ap.add_argument("--holdout",type=int); ap.add_argument("--holdout-start",type=int); ap.add_argument("--holdout-end",type=int); ap.add_argument("--policy",default="config/nfl_research_search_policy_v1.json"); ap.add_argument("--feature-set",choices=("baseline","opponent_strength","quarterback"),default="baseline"); ap.add_argument("--out",default="artifacts/football_baselines.json"); args=ap.parse_args()
    policy_path=Path(args.policy)
    try: policy=json.loads(policy_path.read_text())
    except (OSError, json.JSONDecodeError) as exc: raise RuntimeError(f"POLICY_READ_FAILED:{policy_path}:{exc}") from exc
    window=policy.get("immediate_holdout_range")
    if not isinstance(window,list) or len(window)!=2 or not all(isinstance(v,int) for v in window) or window[0]>window[1]: raise RuntimeError("INVALID_POLICY_HOLDOUT_RANGE")
    hold_start,hold_end=window
    supplied=(args.holdout_start,args.holdout_end)
    if args.holdout is not None: supplied=(args.holdout,args.holdout)
    if any(v is not None for v in supplied) and supplied != (hold_start,hold_end): raise RuntimeError(f"HOLDOUT_ARGUMENT_DISAGREES_WITH_POLICY:{supplied}!={(hold_start,hold_end)}")
    training=policy.get("training_seasons_for_immediate_holdout","")
    match=re.fullmatch(r"(\d{4})-(\d{4})",str(training))
    if not match: raise RuntimeError("INVALID_POLICY_TRAINING_WINDOW")
    train_start,train_end=map(int,match.groups())
    if train_end >= hold_start: raise RuntimeError("TRAINING_OVERLAPS_HOLDOUT")
    seasons={int(x) for x in args.seasons.split(",") if x.strip()}; required=set(range(train_start,hold_end+1))
    if not required.issubset(seasons): raise RuntimeError(f"SEASONS_OMIT_POLICY_WINDOW:{sorted(required-seasons)}")
    reports={}
    for sport,loader in (("NFL",nfl),("CFB",cfb)):
        games,sha,source=loader(seasons)
        if not games: raise RuntimeError(f"{sport}: NO_COMPLETED_GAMES")
        # Never train on games after the selected holdout season. A 2019
        # development holdout therefore requires the caller to request
        # pre-2019 seasons (for example 2010,...,2019).
        games=[g for g in games if g["date"][:4].isdigit() and int(g["date"][:4]) <= hold_end]
        if not games: raise RuntimeError(f"{sport}: NO_PRE_HOLDOUT_GAMES")
        global hold_dates,feature_names
        feature_in_use=args.feature_set if sport=="NFL" else "baseline"
        if feature_in_use=="quarterback":
            qb_ready=sum(bool(g.get("home_qb_id")) and bool(g.get("away_qb_id")) for g in games)
            if qb_ready < 120: raise RuntimeError(f"NFL_QUARTERBACK_STARTERS_UNRESOLVED:{qb_ready}")
        X,ym,yt,feature_names,hold_dates=features(games,feature_in_use)
        reports[sport]={"source":source,"source_sha256":sha,"policy_path":str(policy_path),"policy_sha256":hashlib.sha256(policy_path.read_bytes()).hexdigest(),"training_years":[train_start,train_end],"feature_set":feature_in_use,"holdout_years":[hold_start,hold_end],"games_fetched":len(games),"usable_rows":len(X),"status":"RESEARCH_ONLY_NOT_MODEL_P","targets":{"margin":run_target(X,ym,hold_start,hold_end,close_threshold=7 if sport=="NFL" else 14),"total":run_target(X,yt,hold_start,hold_end)}}
        if feature_in_use!="baseline":
            # Same-data control calibration, preregistered and excluded from
            # the feature-attempt budget. It establishes the baseline on 2019.
            X0,_,_,names0,dates0=features(games,"baseline")
            feature_names,hold_dates=names0,dates0
            reports[sport]["control_baseline_same_holdout"]={"budget_counted":False,"reason":"pre_registered_control_calibration","targets":{"margin":run_target(X0,ym,hold_start,hold_end,close_threshold=7 if sport=="NFL" else 14),"total":run_target(X0,yt,hold_start,hold_end)}}
            feature_names,hold_dates=features(games,feature_in_use)[3:]
        if sport=="NFL":
            hold=np.array([hold_start <= int(d[:4]) <= hold_end for d in hold_dates])
            # The feature rows are emitted only after five prior games, so
            # align market rows by the same sorted/usable game order.
            usable=sorted(games,key=lambda z:(z["date"],z["id"]))
            # Rebuild the exact usable keys from the feature pass.
            keys=[]; prior=defaultdict(int)
            for d,grp in groupby(usable,key=lambda z:z["date"]):
                batch=list(grp)
                for g in batch:
                    if prior[g["home"]]>=5 and prior[g["away"]]>=5 and (feature_in_use!="quarterback" or (g.get("home_qb_id") and g.get("away_qb_id"))): keys.append((d,g["id"],g))
                for g in batch: prior[g["home"]]+=1; prior[g["away"]]+=1
            keyed=[g for _,_,g in keys]
            mh=np.array([g.get("spread_line") is not None for g in keyed])
            is_hold=np.array([hold_start <= int(g["date"][:4]) <= hold_end for g in keyed])
            if mh[is_hold].any():
                # nflverse spread_line is already oriented to home margin:
                # positive means the home side is favored. Verify that
                # convention in the report rather than relying on memory.
                spread_pred=np.array([g["spread_line"] if g.get("spread_line") is not None else np.nan for g in keyed])
                total_pred=np.array([g["total_line"] if g.get("total_line") is not None else np.nan for g in keyed])
                for label,pred,yv in (("margin",spread_pred,ym),("total",total_pred,yt)):
                    hold_market=pred[is_hold]
                    hold_actual=yv[is_hold]
                    model_pred=np.asarray(reports[sport]["targets"][label]["holdout_predictions"])
                    if len(model_pred) != len(hold_market):
                        raise RuntimeError(f"BENCHMARK_ALIGNMENT_FAILED:{label}:model={len(model_pred)}:holdout={len(hold_market)}")
                    valid=np.isfinite(hold_market)
                    actual=hold_actual[valid]; estimate=hold_market[valid]; model_pred=model_pred[valid]
                    benchmark={"n_holdout":int(valid.sum()),"rmse":float(np.sqrt(np.mean((estimate-actual)**2))),"source_field":"spread_line" if label=="margin" else "total_line","comparison":"MODEL_VS_CLOSING_LINE_REPORTED_ONLY"}
                    if label=="margin":
                        benchmark["spread_line_home_margin_correlation"]=float(np.corrcoef(estimate,actual)[0,1])
                    benchmark["paired_rmse_bootstrap"]=bootstrap_rmse_delta(model_pred,estimate,actual)
                    reports[sport].setdefault("closing_line_benchmark",{})[label]=benchmark
    out=Path(args.out); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps({"schema":"FOOTBALL_BASELINES_V1","reports":reports},indent=2)+"\n"); print(json.dumps(reports,indent=2)); return 0
if __name__=="__main__": raise SystemExit(main())

