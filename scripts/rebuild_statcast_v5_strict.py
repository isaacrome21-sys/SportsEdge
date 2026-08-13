#!/usr/bin/env python3
"""Strict SportsEdge Statcast V5 rebuild under the committed predeclaration.

2018-2020 raw Statcast contact outcomes pretrain the frozen contact transformer.
2021-2023 train downstream game/first-inning models, 2024 alone selects/calibrates,
and 2025 is the untouched final holdout.
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

from scripts.rebuild_game_nrfi_models import RUN_FEATURES, FI_FEATURES, build_features, fetch_games, get_json, logit, score_distribution, loss, report_rows, metric
from sportsedge.statcast_contact_transformer import fit_frozen_contact_transformer, TRAIN_YEARS as CONTACT_YEARS
from sportsedge.statcast_contract import GAME_STATCAST_FEATURES, NRFI_STATCAST_FEATURES, STATCAST_CONTRACT_VERSION
from sportsedge.statcast_v5_data import parse_savant_csv, build_prior_only_game_features

SAVANT="https://baseballsavant.mlb.com/statcast_search/csv"
V5_YEARS=(2021,2022,2023,2024,2025)
TRANSIENT_HTTP={429,500,502,503,504}


def regular_season_bounds(year:int,cache:Path)->tuple[date,date]:
    """Bind Savant source windows to official MLB regular-season schedule dates."""
    cache.mkdir(parents=True,exist_ok=True); p=cache/f"season_bounds_{year}.json"
    if p.exists(): data=json.loads(p.read_text())
    else:
        data=get_json('/api/v1/schedule',{'sportId':1,'season':year,'gameType':'R'})
        p.write_text(json.dumps(data))
    dates=[]
    for block in data.get('dates') or []:
        for game in block.get('games') or []:
            if str(game.get('gameType'))!='R': continue
            raw=str(game.get('officialDate') or block.get('date') or '')
            try: dates.append(date.fromisoformat(raw))
            except Exception: continue
    if not dates: raise RuntimeError(f"MLB_REGULAR_SEASON_BOUNDS_EMPTY:{year}")
    return min(dates),max(dates)


def _savant_url(year:int,lo:date,hi:date)->str:
    # Match the official Statcast Search parameter family.  The date query is
    # intentionally overlapped; exact bounds are enforced locally after parse.
    params={
        'all':'true','type':'details','player_type':'batter',
        'game_date_gt':(lo-timedelta(days=1)).isoformat(),
        'game_date_lt':(hi+timedelta(days=1)).isoformat(),
        'hfGT':'R|','hfSea':f'{year}|',
        'min_pitches':'0','min_results':'0','min_pas':'0',
        'sort_col':'pitches','player_event_sort':'api_p_release_speed','sort_order':'desc',
    }
    return SAVANT+'?'+urlencode(params)


def _download_savant(year:int,lo:date,hi:date,cache:Path,max_attempts:int=4)->bytes:
    cache.mkdir(parents=True,exist_ok=True); p=cache/f"{lo}_{hi}.csv"
    if p.exists():
        raw=p.read_bytes()
        if b'game_date' in raw[:5000] and b'game_pk' in raw[:5000]: return raw
        p.unlink(missing_ok=True)
    last='UNKNOWN'
    for attempt in range(1,max_attempts+1):
        req=Request(_savant_url(year,lo,hi),headers={
            'Accept':'text/csv,application/csv;q=0.9,*/*;q=0.1',
            'User-Agent':'Mozilla/5.0 (compatible; SportsEdge/5.0; +https://github.com/isaacrome21-sys/SportsEdge)',
            'Referer':'https://baseballsavant.mlb.com/statcast_search',
            'Accept-Language':'en-US,en;q=0.9',
        })
        try:
            with urlopen(req,timeout=180) as r:
                raw=r.read(); status=getattr(r,'status',200); ctype=str(r.headers.get('Content-Type') or '')
            if b'game_date' not in raw[:5000] or b'game_pk' not in raw[:5000]:
                sig=raw[:120].decode('utf-8',errors='replace').replace('\n',' ')[:120]
                last=f"NON_CSV:status={status}:content_type={ctype}:signature={sig!r}"
            else:
                p.write_bytes(raw); return raw
        except HTTPError as exc:
            last=f"HTTP_{exc.code}"
            if exc.code not in TRANSIENT_HTTP: raise
        except (URLError,TimeoutError) as exc:
            last=f"{type(exc).__name__}:{exc}"
        if attempt<max_attempts: time.sleep(min(2**attempt,8))
    raise RuntimeError(f"SAVANT_FETCH_RETRY_EXHAUSTED:{year}:{lo}:{hi}:{last}")


def _fetch_adaptive(year:int,lo:date,hi:date,cache:Path,manifest:list,depth:int=0):
    """Split only source-transport failures; never split/ignore schema failures."""
    try:
        raw=_download_savant(year,lo,hi,cache)
    except RuntimeError as exc:
        if lo>=hi: raise
        span=(hi-lo).days; mid=lo+timedelta(days=span//2)
        print(f"SAVANT_RANGE_SPLIT year={year} lo={lo} hi={hi} reason={exc}",flush=True)
        return _fetch_adaptive(year,lo,mid,cache,manifest,depth+1)+_fetch_adaptive(year,mid+timedelta(days=1),hi,cache,manifest,depth+1)
    sha=hashlib.sha256(raw).hexdigest(); manifest.append({'year':year,'lo':str(lo),'hi':str(hi),'bytes':len(raw),'sha256':sha})
    parsed=parse_savant_csv(raw.decode('utf-8-sig',errors='replace'))
    return [r for r in parsed if lo<=date.fromisoformat(r.game_date)<=hi]


def fetch_savant_year(year:int,cache:Path,bounds_cache:Path):
    """Official Savant transport with retries, adaptive splitting, and exact local bounds."""
    lo,hi=regular_season_bounds(year,bounds_cache); out=[]; manifest=[]
    # Start at seven days; heavy source responses automatically bisect to 1-day.
    cur=lo
    while cur<=hi:
        stop=min(hi,cur+timedelta(days=6))
        out.extend(_fetch_adaptive(year,cur,stop,cache,manifest)); cur=stop+timedelta(days=1)
    keys=[(r.game_pk,r.at_bat_number) for r in out]
    if len(keys)!=len(set(keys)): raise RuntimeError(f"SAVANT_DUPLICATE_PA_AFTER_LOCAL_BOUND:{year}")
    if not out: raise RuntimeError(f"SAVANT_YEAR_EMPTY:{year}")
    mind=min(date.fromisoformat(r.game_date) for r in out); maxd=max(date.fromisoformat(r.game_date) for r in out)
    if mind<lo or maxd>hi: raise RuntimeError(f"SAVANT_LOCAL_DATE_BOUND_VIOLATION:{year}:{mind}:{maxd}:{lo}:{hi}")
    print(f"SAVANT_YEAR_OK year={year} rows={len(out)} source_chunks={len(manifest)} bounds={lo}:{hi}",flush=True)
    return out,manifest


def fit_contact(pa):
    bb=[r for r in pa if r.is_contact]
    if len(bb)<100000: raise RuntimeError(f"CONTACT_PRETRAIN_TOO_SMALL:{len(bb)}")
    X=[[float(r.launch_speed),float(r.launch_angle)] for r in bb]
    return fit_frozen_contact_transformer(X,[int(r.actual_hit) for r in bb],[r.actual_contact_value for r in bb]),len(bb)


def align(legacy,sc_rows):
    by={int(r['game_pk']):r for r in sc_rows if 'blocked' not in r}; rk=[]; rs=[]
    for i,(gid,side) in enumerate(zip(legacy['run_gid'].astype(int),legacy['run_side'].astype(str))):
        row=by.get(int(gid))
        if row is not None: rk.append(i); rs.append([float(row[side][k]) for k in GAME_STATCAST_FEATURES])
    fk=[]; fs=[]
    for i,gid in enumerate(legacy['fi_gid'].astype(int)):
        row=by.get(int(gid))
        if row is not None: fk.append(i); fs.append([float(row['first_inning'][k]) for k in NRFI_STATCAST_FEATURES])
    rk=np.asarray(rk,int); fk=np.asarray(fk,int)
    if not len(rk) or not len(fk): raise RuntimeError('V5_FEATURE_ALIGNMENT_EMPTY')
    out={'run_X':np.column_stack([legacy['run_X'][rk],np.asarray(rs,float)]),'fi_X':np.column_stack([legacy['fi_X'][fk],np.asarray(fs,float)])}
    for k in ('run_y','run_year','run_gid','run_side'): out[k]=legacy[k][rk]
    for k in ('fi_y','fi_year','fi_gid'): out[k]=legacy[k][fk]
    return out


def paired(f,pred,mask):
    sides=f['run_side'].astype(str); years=f['run_year'].astype(int); by={}
    for i,gid in enumerate(f['run_gid'].astype(int)):
        if mask[i]: by.setdefault(gid,{})[sides[i]]=(pred[i],f['run_y'][i],years[i])
    rows=[]
    for gid,v in by.items():
        if 'away' in v and 'home' in v: rows.append((v['away'][0],v['home'][0],v['home'][2],gid,v['away'][1],v['home'][1]))
    return tuple(np.asarray([r[i] for r in rows]) for i in range(6))


def calibrate_ml(rows,calibrator=None):
    raw=np.asarray([r['home_ml'] for r in rows],float)
    if calibrator is None:
        y=np.asarray([r['actual_home_ml'] for r in rows],float)
        calibrator=LogisticRegression(C=100.,solver='lbfgs').fit(logit(raw).reshape(-1,1),y)
    p=calibrator.predict_proba(logit(raw).reshape(-1,1))[:,1]
    out=[]
    for r,pp in zip(rows,p): q=dict(r); q['home_ml']=float(pp); out.append(q)
    return out,calibrator


def main():
    cache=Path(os.getenv('SPORTSEDGE_STATCAST_V5_CACHE','.cache/sportsedge/statcast-v5-strict')); out=Path(os.getenv('SPORTSEDGE_STATCAST_V5_OUT','artifacts/statcast-v5-strict')); out.mkdir(parents=True,exist_ok=True)
    source_manifest=[]; contact_pa=[]; bounds_cache=cache/'statsapi-bounds'
    for y in CONTACT_YEARS:
        rows,m=fetch_savant_year(y,cache/'savant'/str(y),bounds_cache); contact_pa.extend(rows); source_manifest.extend(m)
    transformer,n_contact=fit_contact(contact_pa); tp=out/'sportsedge_contact_transformer_v1.joblib'; joblib.dump(transformer,tp,compress=3); tsha=hashlib.sha256(tp.read_bytes()).hexdigest()
    v5_pa=[]
    for y in V5_YEARS:
        rows,m=fetch_savant_year(y,cache/'savant'/str(y),bounds_cache); v5_pa.extend(rows); source_manifest.extend(m)
    sc=build_prior_only_game_features(v5_pa,transformer,min_team_bbe=75,min_pitcher_bbe=30,min_batter_bbe=20); blocked=sum(1 for r in sc if 'blocked' in r)
    games=fetch_games(cache/'statsapi'); legacy=build_features(games); f=align(legacy,sc)
    rf=tuple(RUN_FEATURES)+tuple(GAME_STATCAST_FEATURES); ff=tuple(FI_FEATURES)+tuple(NRFI_STATCAST_FEATURES)
    ry=f['run_year'].astype(int); train=ry<=2023; cal=ry==2024; hold=ry==2025; sides=f['run_side'].astype(str)
    run_model=HistGradientBoostingRegressor(loss='poisson',learning_rate=.045,max_iter=250,max_leaf_nodes=15,min_samples_leaf=80,l2_regularization=2.0,random_state=531); run_model.fit(f['run_X'][train],f['run_y'][train]); raw=run_model.predict(f['run_X'])
    sa=float(f['run_y'][cal&(sides=='away')].sum()/raw[cal&(sides=='away')].sum()); sh=float(f['run_y'][cal&(sides=='home')].sum()/raw[cal&(sides=='home')].sum()); pred=raw*np.where(sides=='home',sh,sa)
    ca=paired(f,pred,cal); ho=paired(f,pred,hold)
    if len(ho[0])<1000: raise RuntimeError(f"V5_2025_GAME_ROWS_TOO_SMALL:{len(ho[0])}")
    grid=[]
    for alpha in (.10,.18,.26,.34,.42):
        for sigma in (0.,.08,.16,.24): grid.append((loss(score_distribution(*ca,alpha,sigma,800)),alpha,sigma))
    grid.sort(); _,alpha,sigma=grid[0]
    cal_raw=score_distribution(*ca,alpha,sigma,4000); calrows,ml_cal=calibrate_ml(cal_raw)
    hold_raw=score_distribution(*ho,alpha,sigma,6000); holdrows,_=calibrate_ml(hold_raw,ml_cal); gh=report_rows(holdrows)
    fy=f['fi_year'].astype(int); ft=fy<=2023; fc=fy==2024; fh=fy==2025
    if int(fh.sum())<1000: raise RuntimeError(f"V5_2025_FI_ROWS_TOO_SMALL:{int(fh.sum())}")
    fim=HistGradientBoostingClassifier(learning_rate=.04,max_iter=220,max_leaf_nodes=15,min_samples_leaf=100,l2_regularization=3.0,random_state=541); fim.fit(f['fi_X'][ft],f['fi_y'][ft]); praw=fim.predict_proba(f['fi_X'])[:,1]; platt=LogisticRegression(C=100.,solver='lbfgs').fit(logit(praw[fc]).reshape(-1,1),f['fi_y'][fc]); p=platt.predict_proba(logit(praw).reshape(-1,1))[:,1]
    fi_hold=metric(p[fh],f['fi_y'][fh]); buckets=[]
    for lo,hi in ((0,.2),(.2,.4),(.4,.6),(.6,.8),(.8,1.000001)):
        m=fh&(p>=lo)&(p<hi)
        if m.sum()>=30: buckets.append({'lo':lo,'hi':hi,**metric(p[m],f['fi_y'][m])})
    nrfi_ok=fi_hold['z']<=2.5 and max([b['z'] for b in buckets] or [0])<=3.0
    passes={'MONEYLINE':gh['home_ml']['z']<=2.5,'RUN_LINE':max(gh[k]['z'] for k in gh if k.startswith('rl_'))<=2.5,'TOTALS':max(gh[k]['z'] for k in gh if k.startswith('over_'))<=2.5,'NRFI':nrfi_ok,'YRFI':nrfi_ok}
    ga={'version':'GAME_SCORE_V5_STATCAST','run_model':run_model,'run_features':rf,'away_scale':sa,'home_scale':sh,'alpha':alpha,'shared_sigma':sigma,'ml_calibrator':ml_cal,'statcast_contract_version':STATCAST_CONTRACT_VERSION,'statcast_consumed_by_model':True,'statcast_features':GAME_STATCAST_FEATURES,'contact_transformer_sha256':tsha,'train':'2021-2023','calibration':'2024','holdout':'2025'}
    na={'version':'NRFI_V5_STATCAST','model':fim,'calibrator':platt,'features':ff,'statcast_contract_version':STATCAST_CONTRACT_VERSION,'statcast_consumed_by_model':True,'statcast_features':NRFI_STATCAST_FEATURES,'contact_transformer_sha256':tsha,'positive_class':'YRFI','train':'2021-2023','calibration':'2024','holdout':'2025'}
    gp=out/'sportsedge_game_score_v5_statcast.joblib'; npth=out/'sportsedge_nrfi_v5_statcast.joblib'; joblib.dump(ga,gp,compress=3); joblib.dump(na,npth,compress=3)
    report={'schema_version':'statcast_v5_strict_holdout_v1','protocol':'audit/STATCAST_V5_PREDECLARED_PROTOCOL_2026-08-12.md','contact_pretrain_years':list(CONTACT_YEARS),'contact_training_bbe':n_contact,'contact_transformer_sha256':tsha,'game_artifact_sha256':hashlib.sha256(gp.read_bytes()).hexdigest(),'nrfi_artifact_sha256':hashlib.sha256(npth.read_bytes()).hexdigest(),'valid_2025_games':len(ho[0]),'valid_2025_fi':int(fh.sum()),'blocked_games':blocked,'passes':passes,'game_holdout_2025':gh,'fi_holdout_2025':fi_hold,'fi_buckets_2025':buckets,'source_manifest':source_manifest}
    vp=out/'validation.json'; vp.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    manifest={'schema_version':1,'files':[]}
    for q in (tp,gp,npth,vp): manifest['files'].append({'path':str(q),'bytes':q.stat().st_size,'sha256':hashlib.sha256(q.read_bytes()).hexdigest()})
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    print(json.dumps(report,indent=2,sort_keys=True))
    if not all(passes.values()): raise SystemExit('STATCAST_V5_HOLDOUT_FAILED:'+','.join(k for k,v in passes.items() if not v))
    print('STATCAST_V5_STRICT_HOLDOUT_PASS')

if __name__=='__main__': main()
