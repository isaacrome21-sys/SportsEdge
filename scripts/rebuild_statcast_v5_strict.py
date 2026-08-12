#!/usr/bin/env python3
"""Strict SportsEdge Statcast V5 rebuild under the committed predeclaration.

2018-2020 raw Statcast contact outcomes pretrain the frozen contact transformer.
2021-2023 train the downstream game/first-inning models, 2024 alone selects and
calibrates, and 2025 is scored exactly once as final holdout.
"""
from __future__ import annotations
import calendar, hashlib, json, os
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression

from scripts.rebuild_game_nrfi_models import RUN_FEATURES, FI_FEATURES, build_features, fetch_games, logit, score_distribution, loss, report_rows, metric
from sportsedge.statcast_contact_transformer import fit_frozen_contact_transformer, TRAIN_YEARS as CONTACT_YEARS
from sportsedge.statcast_contract import GAME_STATCAST_FEATURES, NRFI_STATCAST_FEATURES, STATCAST_CONTRACT_VERSION
from sportsedge.statcast_v5_data import parse_savant_csv, build_prior_only_game_features

SAVANT="https://baseballsavant.mlb.com/statcast_search/csv"
V5_YEARS=(2021,2022,2023,2024,2025)


def chunks(year,days=14):
    cur=date(year,3,1); end=date(year,11,15)
    while cur<=end:
        hi=min(end,cur+timedelta(days=days-1)); yield cur,hi; cur=hi+timedelta(days=1)


def fetch_savant_year(year:int,cache:Path)->str:
    cache.mkdir(parents=True,exist_ok=True); header=None; rows=[]
    for lo,hi in chunks(year):
        p=cache/f"{lo}_{hi}.csv"
        if not p.exists():
            qlo=lo-timedelta(days=1); qhi=hi+timedelta(days=1)
            url=SAVANT+"?"+urlencode({"all":"true","type":"details","player_type":"batter","game_date_gt":qlo.isoformat(),"game_date_lt":qhi.isoformat(),"hfGT":"R|"})
            with urlopen(Request(url,headers={"Accept":"text/csv","User-Agent":"SportsEdge/5.0"}),timeout=180) as r: raw=r.read()
            if b"game_date" not in raw[:5000] or b"game_pk" not in raw[:5000]: raise RuntimeError(f"SAVANT_NON_CSV:{lo}:{hi}")
            p.write_bytes(raw)
        text=p.read_text(errors="replace"); lines=text.splitlines()
        if not lines: continue
        if header is None: header=lines[0]
        elif lines[0]!=header: raise RuntimeError("SAVANT_HEADER_DRIFT")
        # local exact-date filter happens through parser rows below; overlap is intentional
        rows.extend(lines[1:])
    if header is None: raise RuntimeError(f"SAVANT_YEAR_EMPTY:{year}")
    parsed=parse_savant_csv(header+"\n"+"\n".join(rows)+"\n")
    parsed=[r for r in parsed if int(r.game_date[:4])==year]
    # Re-serialize only canonical fields accepted by parse_savant_csv.
    cols=("game_date","game_pk","batter","pitcher","events","home_team","away_team","inning","inning_topbot","at_bat_number","launch_speed","launch_angle","launch_speed_angle")
    out=[",".join(cols)]
    for r in parsed:
        vals=[r.game_date,r.game_pk,r.batter,r.pitcher,r.event,r.home_team,r.away_team,r.inning,r.topbot,r.at_bat_number,"" if r.launch_speed is None else r.launch_speed,"" if r.launch_angle is None else r.launch_angle,"" if r.launch_speed_angle is None else r.launch_speed_angle]
        out.append(",".join(str(v) for v in vals))
    return "\n".join(out)+"\n"


def fit_contact(pa):
    bb=[r for r in pa if r.is_contact]
    if len(bb)<100000: raise RuntimeError(f"CONTACT_PRETRAIN_TOO_SMALL:{len(bb)}")
    X=[[float(r.launch_speed),float(r.launch_angle)] for r in bb]
    return fit_frozen_contact_transformer(X,[int(r.actual_hit) for r in bb],[r.actual_contact_value for r in bb]),len(bb)


def align(legacy,sc_rows):
    by={int(r["game_pk"]):r for r in sc_rows if "blocked" not in r}
    rk=[]; rs=[]
    for i,(gid,side) in enumerate(zip(legacy["run_gid"].astype(int),legacy["run_side"].astype(str))):
        row=by.get(int(gid))
        if row is not None: rk.append(i); rs.append([float(row[side][k]) for k in GAME_STATCAST_FEATURES])
    fk=[]; fs=[]
    for i,gid in enumerate(legacy["fi_gid"].astype(int)):
        row=by.get(int(gid))
        if row is not None: fk.append(i); fs.append([float(row["first_inning"][k]) for k in NRFI_STATCAST_FEATURES])
    rk=np.asarray(rk,int); fk=np.asarray(fk,int); out={}
    out["run_X"]=np.column_stack([legacy["run_X"][rk],np.asarray(rs,float)]); out["fi_X"]=np.column_stack([legacy["fi_X"][fk],np.asarray(fs,float)])
    for k in ("run_y","run_year","run_gid","run_side"): out[k]=legacy[k][rk]
    for k in ("fi_y","fi_year","fi_gid"): out[k]=legacy[k][fk]
    return out


def paired(f,pred,mask):
    sides=f["run_side"].astype(str); years=f["run_year"].astype(int); by={}
    for i,gid in enumerate(f["run_gid"].astype(int)):
        if mask[i]: by.setdefault(gid,{})[sides[i]]=(pred[i],f["run_y"][i],years[i])
    rows=[]
    for gid,v in by.items():
        if "away" in v and "home" in v: rows.append((v["away"][0],v["home"][0],v["home"][2],gid,v["away"][1],v["home"][1]))
    return tuple(np.asarray([r[i] for r in rows]) for i in range(6))


def main():
    cache=Path(os.getenv("SPORTSEDGE_STATCAST_V5_CACHE",".cache/sportsedge/statcast-v5-strict")); out=Path(os.getenv("SPORTSEDGE_STATCAST_V5_OUT","artifacts/statcast-v5-strict")); out.mkdir(parents=True,exist_ok=True)
    contact_texts=[fetch_savant_year(y,cache/"savant"/str(y)) for y in CONTACT_YEARS]
    contact_pa=[]
    for t in contact_texts: contact_pa.extend(parse_savant_csv(t))
    transformer,n_contact=fit_contact(contact_pa); tp=out/"sportsedge_contact_transformer_v1.joblib"; joblib.dump(transformer,tp,compress=3); tsha=hashlib.sha256(tp.read_bytes()).hexdigest()
    v5_pa=[]
    for y in V5_YEARS: v5_pa.extend(parse_savant_csv(fetch_savant_year(y,cache/"savant"/str(y))))
    sc=build_prior_only_game_features(v5_pa,transformer,min_team_bbe=75,min_pitcher_bbe=30,min_batter_bbe=20)
    blocked=sum(1 for r in sc if "blocked" in r)
    games=fetch_games(cache/"statsapi"); legacy=build_features(games); f=align(legacy,sc)
    rf=tuple(RUN_FEATURES)+tuple(GAME_STATCAST_FEATURES); ff=tuple(FI_FEATURES)+tuple(NRFI_STATCAST_FEATURES)
    ry=f["run_year"].astype(int); train=ry<=2023; cal=ry==2024; hold=ry==2025; sides=f["run_side"].astype(str)
    run_model=HistGradientBoostingRegressor(loss="poisson",learning_rate=.045,max_iter=250,max_leaf_nodes=15,min_samples_leaf=80,l2_regularization=2.0,random_state=531); run_model.fit(f["run_X"][train],f["run_y"][train]); raw=run_model.predict(f["run_X"])
    sa=float(f["run_y"][cal&(sides=="away")].sum()/raw[cal&(sides=="away")].sum()); sh=float(f["run_y"][cal&(sides=="home")].sum()/raw[cal&(sides=="home")].sum()); pred=raw*np.where(sides=="home",sh,sa)
    ca=paired(f,pred,cal); ho=paired(f,pred,hold)
    if len(ho[0])<1000: raise RuntimeError(f"V5_2025_GAME_ROWS_TOO_SMALL:{len(ho[0])}")
    grid=[]
    for alpha in (.10,.18,.26,.34,.42):
        for sigma in (0.,.08,.16,.24): grid.append((loss(score_distribution(*ca,alpha,sigma,800)),alpha,sigma))
    grid.sort(); _,alpha,sigma=grid[0]; calrows=score_distribution(*ca,alpha,sigma,4000); holdrows=score_distribution(*ho,alpha,sigma,6000); gh=report_rows(holdrows)
    fy=f["fi_year"].astype(int); ft=fy<=2023; fc=fy==2024; fh=fy==2025
    if int(fh.sum())<1000: raise RuntimeError(f"V5_2025_FI_ROWS_TOO_SMALL:{int(fh.sum())}")
    fim=HistGradientBoostingClassifier(learning_rate=.04,max_iter=220,max_leaf_nodes=15,min_samples_leaf=100,l2_regularization=3.0,random_state=541); fim.fit(f["fi_X"][ft],f["fi_y"][ft]); praw=fim.predict_proba(f["fi_X"])[:,1]; platt=LogisticRegression(C=100.,solver="lbfgs").fit(logit(praw[fc]).reshape(-1,1),f["fi_y"][fc]); p=platt.predict_proba(logit(praw).reshape(-1,1))[:,1]
    fi_hold=metric(p[fh],f["fi_y"][fh]); buckets=[]
    for lo,hi in ((0,.2),(.2,.4),(.4,.6),(.6,.8),(.8,1.000001)):
        m=fh&(p>=lo)&(p<hi)
        if m.sum()>=30: buckets.append({"lo":lo,"hi":hi,**metric(p[m],f["fi_y"][m])})
    passes={"MONEYLINE":gh["home_ml"]["z"]<=2.5,"RUN_LINE":max(gh[k]["z"] for k in gh if k.startswith("rl_"))<=2.5,"TOTALS":max(gh[k]["z"] for k in gh if k.startswith("over_"))<=2.5,"NRFI":fi_hold["z"]<=2.5 and max([b["z"] for b in buckets] or [0])<=3.0,"YRFI":fi_hold["z"]<=2.5 and max([b["z"] for b in buckets] or [0])<=3.0}
    ga={"version":"GAME_SCORE_V5_STATCAST","run_model":run_model,"run_features":rf,"away_scale":sa,"home_scale":sh,"alpha":alpha,"shared_sigma":sigma,"statcast_contract_version":STATCAST_CONTRACT_VERSION,"statcast_consumed_by_model":True,"statcast_features":GAME_STATCAST_FEATURES,"contact_transformer_sha256":tsha,"train":"2021-2023","calibration":"2024","holdout":"2025"}
    na={"version":"NRFI_V5_STATCAST","model":fim,"calibrator":platt,"features":ff,"statcast_contract_version":STATCAST_CONTRACT_VERSION,"statcast_consumed_by_model":True,"statcast_features":NRFI_STATCAST_FEATURES,"contact_transformer_sha256":tsha,"positive_class":"YRFI","train":"2021-2023","calibration":"2024","holdout":"2025"}
    gp=out/"sportsedge_game_score_v5_statcast.joblib"; npth=out/"sportsedge_nrfi_v5_statcast.joblib"; joblib.dump(ga,gp,compress=3); joblib.dump(na,npth,compress=3)
    report={"schema_version":"statcast_v5_strict_holdout_v1","protocol_commit_precedes_fit":True,"contact_pretrain_years":list(CONTACT_YEARS),"contact_training_bbe":n_contact,"contact_transformer_sha256":tsha,"game_artifact_sha256":hashlib.sha256(gp.read_bytes()).hexdigest(),"nrfi_artifact_sha256":hashlib.sha256(npth.read_bytes()).hexdigest(),"valid_2025_games":len(ho[0]),"valid_2025_fi":int(fh.sum()),"blocked_games":blocked,"passes":passes,"game_holdout_2025":gh,"fi_holdout_2025":fi_hold,"fi_buckets_2025":buckets}
    vp=out/"validation.json"; vp.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    manifest={"schema_version":1,"files":[]}
    for q in (tp,gp,npth,vp): manifest["files"].append({"path":str(q),"bytes":q.stat().st_size,"sha256":hashlib.sha256(q.read_bytes()).hexdigest()})
    (out/"manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n")
    print(json.dumps(report,indent=2,sort_keys=True))
    if not all(passes.values()): raise SystemExit("STATCAST_V5_HOLDOUT_FAILED:"+",".join(k for k,v in passes.items() if not v))
    print("STATCAST_V5_STRICT_HOLDOUT_PASS")

if __name__=="__main__": main()
