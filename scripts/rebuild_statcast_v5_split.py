#!/usr/bin/env python3
"""Optimized but feature-equivalent Statcast V5 rebuild.

Full-game contact rows update rolling contact state. First-inning PA rows supply
only target-game starter/top-three identities. Both feeds are official Savant,
date-bounded, retried, adaptively split, hashed, and never use Savant expected
statistics. The downstream fitting/holdout rules are identical to the strict V5
predeclaration.
"""
from __future__ import annotations

import hashlib, json, os, time
from datetime import date, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression

import scripts.rebuild_statcast_v5_strict as s
from sportsedge.statcast_contact_transformer import TRAIN_YEARS as CONTACT_YEARS
from sportsedge.statcast_contract import GAME_STATCAST_FEATURES, NRFI_STATCAST_FEATURES, STATCAST_CONTRACT_VERSION
from sportsedge.statcast_v5_data import parse_savant_csv
from sportsedge.statcast_v5_split import build_prior_only_game_features_split
from scripts.rebuild_game_nrfi_models import RUN_FEATURES, FI_FEATURES, build_features, fetch_games, logit, score_distribution, loss, report_rows, metric

SAVANT=s.SAVANT
V5_YEARS=s.V5_YEARS
TRANSIENT_HTTP=s.TRANSIENT_HTTP
CONTACT_BBT='ground_ball|line_drive|fly_ball|popup|'


def _url(year:int,lo:date,hi:date,mode:str)->str:
    params={
        'all':'true','type':'details','player_type':'batter',
        'game_date_gt':(lo-timedelta(days=1)).isoformat(),
        'game_date_lt':(hi+timedelta(days=1)).isoformat(),
        'hfGT':'R|','hfSea':f'{year}|','min_pitches':'0','min_results':'0','min_pas':'0',
        'sort_col':'pitches','player_event_sort':'api_p_release_speed','sort_order':'desc',
    }
    if mode=='contact': params['hfBBT']=CONTACT_BBT
    elif mode=='identity': params['hfInn']='1|'
    else: raise ValueError('STATCAST_SPLIT_MODE_INVALID')
    return SAVANT+'?'+urlencode(params)


def _download(year:int,lo:date,hi:date,mode:str,cache:Path,max_attempts:int=4)->bytes:
    cache.mkdir(parents=True,exist_ok=True); p=cache/f'{mode}_{lo}_{hi}.csv'
    if p.exists():
        raw=p.read_bytes()
        if b'game_date' in raw[:5000] and b'game_pk' in raw[:5000]: return raw
        p.unlink(missing_ok=True)
    last='UNKNOWN'
    for attempt in range(1,max_attempts+1):
        req=Request(_url(year,lo,hi,mode),headers={
            'Accept':'text/csv,application/csv;q=0.9,*/*;q=0.1',
            'User-Agent':'Mozilla/5.0 (compatible; SportsEdge/5.0)',
            'Referer':'https://baseballsavant.mlb.com/statcast_search','Accept-Language':'en-US,en;q=0.9',
        })
        try:
            with urlopen(req,timeout=150) as r: raw=r.read()
            if b'game_date' in raw[:5000] and b'game_pk' in raw[:5000]: p.write_bytes(raw); return raw
            last='NON_CSV:'+raw[:100].decode('utf-8',errors='replace').replace('\n',' ')
        except HTTPError as exc:
            last=f'HTTP_{exc.code}'
            if exc.code not in TRANSIENT_HTTP: raise
        except (URLError,TimeoutError) as exc: last=f'{type(exc).__name__}:{exc}'
        if attempt<max_attempts: time.sleep(min(2**attempt,8))
    raise RuntimeError(f'SAVANT_SPLIT_FETCH_EXHAUSTED:{mode}:{year}:{lo}:{hi}:{last}')


def _adaptive(year:int,lo:date,hi:date,mode:str,cache:Path,manifest:list):
    try: raw=_download(year,lo,hi,mode,cache)
    except RuntimeError as exc:
        if lo>=hi: raise
        mid=lo+timedelta(days=(hi-lo).days//2)
        print(f'SAVANT_SPLIT_RANGE mode={mode} year={year} lo={lo} hi={hi} reason={exc}',flush=True)
        return _adaptive(year,lo,mid,mode,cache,manifest)+_adaptive(year,mid+timedelta(days=1),hi,mode,cache,manifest)
    manifest.append({'feed':mode,'year':year,'lo':str(lo),'hi':str(hi),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
    rows=parse_savant_csv(raw.decode('utf-8-sig',errors='replace'))
    return [r for r in rows if lo<=date.fromisoformat(r.game_date)<=hi]


def fetch_feed(year:int,mode:str,cache:Path,bounds_cache:Path):
    lo,hi=s.regular_season_bounds(year,bounds_cache); out=[]; manifest=[]; cur=lo
    # Contact and first-inning payloads are much smaller, so start at 14 days.
    while cur<=hi:
        stop=min(hi,cur+timedelta(days=13)); out.extend(_adaptive(year,cur,stop,mode,cache,manifest)); cur=stop+timedelta(days=1)
    keys=[(r.game_pk,r.at_bat_number) for r in out]
    if len(keys)!=len(set(keys)): raise RuntimeError(f'SAVANT_SPLIT_DUPLICATE_PA:{mode}:{year}')
    if not out: raise RuntimeError(f'SAVANT_SPLIT_EMPTY:{mode}:{year}')
    if mode=='identity' and any(int(r.inning)!=1 for r in out): raise RuntimeError(f'SAVANT_IDENTITY_FEED_INNING_VIOLATION:{year}')
    if mode=='contact' and any(not r.is_contact for r in out): raise RuntimeError(f'SAVANT_CONTACT_FEED_NONCONTACT:{year}')
    print(f'SAVANT_SPLIT_YEAR_OK feed={mode} year={year} rows={len(out)} chunks={len(manifest)}',flush=True)
    return out,manifest


def train_models(f,transformer,tsha:str,state,source_manifest:list,out:Path,contact_n:int):
    rf=tuple(RUN_FEATURES)+tuple(GAME_STATCAST_FEATURES); ff=tuple(FI_FEATURES)+tuple(NRFI_STATCAST_FEATURES)
    ry=f['run_year'].astype(int); train=ry<=2023; cal=ry==2024; hold=ry==2025; sides=f['run_side'].astype(str)
    run_model=HistGradientBoostingRegressor(loss='poisson',learning_rate=.045,max_iter=250,max_leaf_nodes=15,min_samples_leaf=80,l2_regularization=2.0,random_state=531)
    run_model.fit(f['run_X'][train],f['run_y'][train]); raw=run_model.predict(f['run_X'])
    sa=float(f['run_y'][cal&(sides=='away')].sum()/raw[cal&(sides=='away')].sum()); sh=float(f['run_y'][cal&(sides=='home')].sum()/raw[cal&(sides=='home')].sum()); pred=raw*np.where(sides=='home',sh,sa)
    ca=s.paired(f,pred,cal); ho=s.paired(f,pred,hold)
    if len(ho[0])<1000: raise RuntimeError(f'V5_2025_GAME_ROWS_TOO_SMALL:{len(ho[0])}')
    grid=[]
    for alpha in (.10,.18,.26,.34,.42):
        for sigma in (0.,.08,.16,.24): grid.append((loss(score_distribution(*ca,alpha,sigma,800)),alpha,sigma))
    grid.sort(); _,alpha,sigma=grid[0]
    cal_raw=score_distribution(*ca,alpha,sigma,4000); _,ml_cal=s.calibrate_ml(cal_raw)
    hold_raw=score_distribution(*ho,alpha,sigma,6000); holdrows,_=s.calibrate_ml(hold_raw,ml_cal); gh=report_rows(holdrows)
    fy=f['fi_year'].astype(int); ft=fy<=2023; fc=fy==2024; fh=fy==2025
    if int(fh.sum())<1000: raise RuntimeError(f'V5_2025_FI_ROWS_TOO_SMALL:{int(fh.sum())}')
    fim=HistGradientBoostingClassifier(learning_rate=.04,max_iter=220,max_leaf_nodes=15,min_samples_leaf=100,l2_regularization=3.0,random_state=541); fim.fit(f['fi_X'][ft],f['fi_y'][ft])
    praw=fim.predict_proba(f['fi_X'])[:,1]; platt=LogisticRegression(C=100.,solver='lbfgs').fit(logit(praw[fc]).reshape(-1,1),f['fi_y'][fc]); p=platt.predict_proba(logit(praw).reshape(-1,1))[:,1]
    fi_hold=metric(p[fh],f['fi_y'][fh]); buckets=[]
    for lo,hi in ((0,.2),(.2,.4),(.4,.6),(.6,.8),(.8,1.000001)):
        m=fh&(p>=lo)&(p<hi)
        if m.sum()>=30: buckets.append({'lo':lo,'hi':hi,**metric(p[m],f['fi_y'][m])})
    nrfi_ok=fi_hold['z']<=2.5 and max([b['z'] for b in buckets] or [0])<=3.0
    passes={'MONEYLINE':gh['home_ml']['z']<=2.5,'RUN_LINE':max(gh[k]['z'] for k in gh if k.startswith('rl_'))<=2.5,'TOTALS':max(gh[k]['z'] for k in gh if k.startswith('over_'))<=2.5,'NRFI':nrfi_ok,'YRFI':nrfi_ok}
    ga={'version':'GAME_SCORE_V5_STATCAST','run_model':run_model,'run_features':rf,'away_scale':sa,'home_scale':sh,'alpha':alpha,'shared_sigma':sigma,'ml_calibrator':ml_cal,'statcast_contract_version':STATCAST_CONTRACT_VERSION,'statcast_consumed_by_model':True,'statcast_features':GAME_STATCAST_FEATURES,'contact_transformer_sha256':tsha,'train':'2021-2023','calibration':'2024','holdout':'2025'}
    na={'version':'NRFI_V5_STATCAST','model':fim,'calibrator':platt,'features':ff,'statcast_contract_version':STATCAST_CONTRACT_VERSION,'statcast_consumed_by_model':True,'statcast_features':NRFI_STATCAST_FEATURES,'contact_transformer_sha256':tsha,'positive_class':'YRFI','train':'2021-2023','calibration':'2024','holdout':'2025'}
    tp=out/'sportsedge_contact_transformer_v1.joblib'; gp=out/'sportsedge_game_score_v5_statcast.joblib'; npth=out/'sportsedge_nrfi_v5_statcast.joblib'; sp=out/'sportsedge_statcast_state_end_2025.joblib'
    joblib.dump(transformer,tp,compress=3); joblib.dump(ga,gp,compress=3); joblib.dump(na,npth,compress=3); joblib.dump(state,sp,compress=3)
    report={'schema_version':'statcast_v5_split_holdout_v1','protocol':'audit/STATCAST_V5_PREDECLARED_PROTOCOL_2026-08-12.md','contact_pretrain_years':list(CONTACT_YEARS),'contact_training_bbe':contact_n,'contact_transformer_sha256':tsha,'game_artifact_sha256':hashlib.sha256(gp.read_bytes()).hexdigest(),'nrfi_artifact_sha256':hashlib.sha256(npth.read_bytes()).hexdigest(),'base_state_end_2025_sha256':hashlib.sha256(sp.read_bytes()).hexdigest(),'valid_2025_games':len(ho[0]),'valid_2025_fi':int(fh.sum()),'passes':passes,'game_holdout_2025':gh,'fi_holdout_2025':fi_hold,'fi_buckets_2025':buckets,'source_manifest':source_manifest}
    vp=out/'validation.json'; vp.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    manifest={'schema_version':1,'files':[]}
    for q in (tp,gp,npth,sp,vp): manifest['files'].append({'path':str(q),'bytes':q.stat().st_size,'sha256':hashlib.sha256(q.read_bytes()).hexdigest()})
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    print(json.dumps(report,indent=2,sort_keys=True))
    if not all(passes.values()): raise SystemExit('STATCAST_V5_HOLDOUT_FAILED:'+','.join(k for k,v in passes.items() if not v))
    print('STATCAST_V5_SPLIT_HOLDOUT_PASS')


def main():
    cache=Path(os.getenv('SPORTSEDGE_STATCAST_V5_CACHE','.cache/sportsedge/statcast-v5-split')); out=Path(os.getenv('SPORTSEDGE_STATCAST_V5_OUT','artifacts/statcast-v5-strict')); out.mkdir(parents=True,exist_ok=True); bounds=cache/'statsapi-bounds'; manifest=[]
    pretrain=[]
    for y in CONTACT_YEARS:
        rows,m=fetch_feed(y,'contact',cache/'savant'/str(y),bounds); pretrain.extend(rows); manifest.extend(m)
    transformer,contact_n=s.fit_contact(pretrain); tp=out/'sportsedge_contact_transformer_v1.joblib'; joblib.dump(transformer,tp,compress=3); tsha=hashlib.sha256(tp.read_bytes()).hexdigest()
    identity=[]; contacts=[]
    for y in V5_YEARS:
        a,m=fetch_feed(y,'identity',cache/'savant'/str(y),bounds); identity.extend(a); manifest.extend(m)
        b,m=fetch_feed(y,'contact',cache/'savant'/str(y),bounds); contacts.extend(b); manifest.extend(m)
    sc,state=build_prior_only_game_features_split(identity,contacts,transformer,min_team_bbe=75,min_pitcher_bbe=30,min_batter_bbe=20)
    games=fetch_games(cache/'statsapi'); legacy=build_features(games); f=s.align(legacy,sc)
    train_models(f,transformer,tsha,state,manifest,out,contact_n)

if __name__=='__main__': main()
