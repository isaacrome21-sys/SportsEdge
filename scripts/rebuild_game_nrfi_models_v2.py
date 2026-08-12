#!/usr/bin/env python3
"""Second predeclared core-market rebuild after 2025 became calibration data.

Protocol fixed before 2026 inspection:
- fit 2021-2024
- calibrate run distribution, ML Platt layer, and YRFI Platt layer on 2025
- final untouched holdout: 2026 regular-season finals through 2026-08-10
"""
from __future__ import annotations
import json
from pathlib import Path
import joblib, numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression
import scripts.rebuild_game_nrfi_models as core

core.YEARS=(2021,2022,2023,2024,2025,2026)
def ranges(y):
    if y != 2026:
        yield from core.month_ranges(y); return
    import calendar
    for m in range(3,8):
        yield f'{y}-{m:02d}-01',f'{y}-{m:02d}-{calendar.monthrange(y,m)[1]:02d}'
    yield '2026-08-01','2026-08-10'
core.month_ranges=ranges

def buckets(p,y):
    out=[];p=np.asarray(p);y=np.asarray(y)
    for lo,hi in ((0,.2),(.2,.4),(.4,.6),(.6,.8),(.8,1.000001)):
        m=(p>=lo)&(p<hi)
        if m.sum()>=30:out.append({'lo':lo,'hi':hi,**core.metric(p[m],y[m])})
    return out

def main():
    games=core.fetch_games(Path('.cache/sportsedge/game-rebuild-v2/schedule'));f=core.build_features(games)
    ry=f['run_year'].astype(int); train=ry<=2024; cal=ry==2025; hold=ry==2026; sides=f['run_side'].astype(str)
    rm=HistGradientBoostingRegressor(loss='poisson',learning_rate=.045,max_iter=250,max_leaf_nodes=15,min_samples_leaf=80,l2_regularization=2.,random_state=31);rm.fit(f['run_X'][train],f['run_y'][train]);rawmu=rm.predict(f['run_X'])
    sa=float(f['run_y'][cal&(sides=='away')].sum()/rawmu[cal&(sides=='away')].sum());sh=float(f['run_y'][cal&(sides=='home')].sum()/rawmu[cal&(sides=='home')].sum());mu=rawmu*np.where(sides=='home',sh,sa)
    def arr(mask):
        by={}
        for i,gid in enumerate(f['run_gid'].astype(int)):
            if mask[i]:by.setdefault(gid,{})[sides[i]]=(mu[i],f['run_y'][i],ry[i])
        ma=[];mh=[];yrs=[];gids=[];aa=[];hh=[]
        for gid,v in by.items():
            if {'away','home'}<=set(v):ma.append(v['away'][0]);mh.append(v['home'][0]);aa.append(v['away'][1]);hh.append(v['home'][1]);yrs.append(v['home'][2]);gids.append(gid)
        return tuple(np.asarray(x) for x in (ma,mh,yrs,gids,aa,hh))
    ca=arr(cal);ho=arr(hold);grid=[]
    for a in (.10,.18,.26,.34,.42):
        for s in (0.,.08,.16,.24):
            r=core.score_distribution(*ca,a,s,800);grid.append((core.loss(r),a,s))
    grid.sort();_,alpha,sigma=grid[0];cr=core.score_distribution(*ca,alpha,sigma,5000);hr=core.score_distribution(*ho,alpha,sigma,7000)
    cp=np.array([r['home_ml'] for r in cr]);cy=np.array([r['actual_home_ml'] for r in cr]);hp=np.array([r['home_ml'] for r in hr]);hy=np.array([r['actual_home_ml'] for r in hr]);mlcal=LogisticRegression(C=100.,solver='lbfgs').fit(core.logit(cp).reshape(-1,1),cy);hpc=mlcal.predict_proba(core.logit(hp).reshape(-1,1))[:,1]
    ghold=core.report_rows(hr);mlm=core.metric(hpc,hy);mlb=buckets(hpc,hy);ml_pass=mlm['z']<=2.5 and max([b['z'] for b in mlb] or [0])<=3.;rl_pass=max(ghold[k]['z'] for k in ghold if k.startswith('rl_'))<=2.5;total_pass=max(ghold[k]['z'] for k in ghold if k.startswith('over_'))<=2.5
    fy=f['fi_year'].astype(int);ft=fy<=2024;fc=fy==2025;fh=fy==2026;fm=HistGradientBoostingClassifier(learning_rate=.04,max_iter=220,max_leaf_nodes=15,min_samples_leaf=100,l2_regularization=3.,random_state=41);fm.fit(f['fi_X'][ft],f['fi_y'][ft]);fr=fm.predict_proba(f['fi_X'])[:,1];fcal=LogisticRegression(C=100.,solver='lbfgs').fit(core.logit(fr[fc]).reshape(-1,1),f['fi_y'][fc]);fp=fcal.predict_proba(core.logit(fr[fh]).reshape(-1,1))[:,1];fmtr=core.metric(fp,f['fi_y'][fh]);fb=buckets(fp,f['fi_y'][fh]);fi_pass=fmtr['z']<=2.5 and max([b['z'] for b in fb] or [0])<=3.
    val={'schema_version':'core_game_markets_rebuild_v2','source':'MLB_STATSAPI_ONLY_NO_SPORTSBOOK_FEATURES','train':'2021-2024','calibration':'2025','final_holdout':'2026-03-01_to_2026-08-10','markets':{'MONEYLINE':{'pass':ml_pass,'metrics':mlm,'holdout_buckets':mlb},'RUN_LINE':{'pass':rl_pass,'metrics':{k:v for k,v in ghold.items() if k.startswith('rl_')}},'TOTALS':{'pass':total_pass,'metrics':{k:v for k,v in ghold.items() if k.startswith('over_')}},'NRFI_YRFI':{'pass':fi_pass,'metrics':fmtr,'holdout_buckets':fb}},'selected_on_2025':{'alpha':alpha,'shared_sigma':sigma,'away_scale':sa,'home_scale':sh},'holdout_games':len(hr)}
    art=Path('artifacts');art.mkdir(exist_ok=True);joblib.dump({'version':'GAME_SCORE_V3','run_model':rm,'run_features':core.RUN_FEATURES,'away_scale':sa,'home_scale':sh,'alpha':alpha,'shared_sigma':sigma,'ml_calibrator':mlcal,'feature_policy':'prior_only_team_history'},art/'sportsedge_game_score_v3.joblib');joblib.dump({'version':'NRFI_V3','model':fm,'calibrator':fcal,'features':core.FI_FEATURES,'feature_policy':'prior_only_team_first_inning_history'},art/'sportsedge_nrfi_v3.joblib');(art/'core_game_markets_validation_v2.json').write_text(json.dumps(val,indent=2,sort_keys=True)+'\n');print(json.dumps({'holdout_games':len(hr),'passes':{k:v['pass'] for k,v in val['markets'].items()},'selected':val['selected_on_2025']},indent=2));return 0 if all(v['pass'] for v in val['markets'].values()) else 2
if __name__=='__main__':raise SystemExit(main())
