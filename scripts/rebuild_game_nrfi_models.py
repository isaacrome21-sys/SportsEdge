#!/usr/bin/env python3
"""Rebuild ML/RL/totals and NRFI/YRFI from official MLB prior-only history.

Model-selection policy is fixed before the 2025 final holdout is scored:
- fit 2021-2023
- calibrate distribution/Platt state on 2024
- evaluate exactly once on untouched 2025
Sportsbook prices/probabilities are never fetched or used.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import calendar, json, math, os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression

BASE='https://statsapi.mlb.com'
YEARS=(2021,2022,2023,2024,2025)
RUN_PRIOR=4.4
FI_PRIOR=0.28
PRIOR_GAMES=20.0
RUN_FEATURES=('off_rf_pg','opp_ra_pg','off_ewm_rf','opp_ewm_ra','league_runs_pg','home_flag','rest_days','season_games','month_sin','month_cos')
FI_FEATURES=('away_fi_for','home_fi_for','home_fi_against','away_fi_against','away_ewm_fi_for','home_ewm_fi_for','home_ewm_fi_against','away_ewm_fi_against','away_rf_pg','home_rf_pg','home_ra_pg','away_ra_pg','league_fi_rate','away_rest','home_rest','month_sin','month_cos')

@dataclass
class TeamState:
    n:int=0; rf:float=0; ra:float=0; fi_for:float=0; fi_against:float=0
    ewm_rf:float=RUN_PRIOR; ewm_ra:float=RUN_PRIOR
    ewm_fi_for:float=FI_PRIOR; ewm_fi_against:float=FI_PRIOR
    last_date:date|None=None


def get_json(path,params):
    u=f'{BASE}{path}?{urlencode(params)}'
    with urlopen(Request(u,headers={'Accept':'application/json'}),timeout=60) as r:
        return json.loads(r.read().decode())


def month_ranges(year):
    for m in range(3,11):
        last=calendar.monthrange(year,m)[1]
        yield f'{year}-{m:02d}-01',f'{year}-{m:02d}-{last:02d}'


def fetch_games(cache_dir:Path):
    cache_dir.mkdir(parents=True,exist_ok=True)
    by_pk={}
    for y in YEARS:
        for start,end in month_ranges(y):
            p=cache_dir/f'schedule_{start}_{end}.json'
            if p.exists(): data=json.loads(p.read_text())
            else:
                data=get_json('/api/v1/schedule',{'sportId':1,'startDate':start,'endDate':end,'hydrate':'linescore,team'})
                p.write_text(json.dumps(data))
            for db in data.get('dates') or []:
                for g in db.get('games') or []:
                    if str(g.get('gameType'))!='R': continue
                    if (g.get('status') or {}).get('abstractGameState')!='Final': continue
                    ls=g.get('linescore') or {}; teams=g.get('teams') or {}
                    try:
                        hr=int(((ls.get('teams') or {}).get('home') or {})['runs']); ar=int(((ls.get('teams') or {}).get('away') or {})['runs'])
                        hid=int(((teams.get('home') or {}).get('team') or {})['id']); aid=int(((teams.get('away') or {}).get('team') or {})['id'])
                        d=date.fromisoformat(str(g.get('officialDate') or db.get('date')))
                    except Exception: continue
                    first=next((x for x in (ls.get('innings') or []) if int(x.get('num') or 0)==1),None)
                    if not first: continue
                    try: afi=int((first.get('away') or {}).get('runs',0)); hfi=int((first.get('home') or {}).get('runs',0))
                    except Exception: continue
                    by_pk[int(g['gamePk'])]={'game_pk':int(g['gamePk']),'date':d.isoformat(),'year':y,'month':d.month,'away_id':aid,'home_id':hid,'away_runs':ar,'home_runs':hr,'away_fi':afi,'home_fi':hfi}
    return sorted(by_pk.values(),key=lambda x:(x['date'],x['game_pk']))


def smooth(num,n,prior): return (num+PRIOR_GAMES*prior)/(n+PRIOR_GAMES)
def rest(st:TeamState,d:date):
    if st.last_date is None:return 4.0
    return float(min(max((d-st.last_date).days,0),7))


def build_features(games):
    states={}; league_n=0; league_runs=0.0; league_fi_events=0.0
    run_X=[]; run_y=[]; run_year=[]; run_gid=[]; run_side=[]; fi_X=[]; fi_y=[]; fi_year=[]; fi_gid=[]
    for g in games:
        d=date.fromisoformat(g['date']); a=states.setdefault(g['away_id'],TeamState()); h=states.setdefault(g['home_id'],TeamState())
        lg_run=(league_runs+PRIOR_GAMES*2*RUN_PRIOR)/(2*league_n+PRIOR_GAMES*2) if league_n else RUN_PRIOR
        lg_fi=(league_fi_events+PRIOR_GAMES*2*FI_PRIOR)/(2*league_n+PRIOR_GAMES*2) if league_n else FI_PRIOR
        ms=math.sin(2*math.pi*d.timetuple().tm_yday/365.25); mc=math.cos(2*math.pi*d.timetuple().tm_yday/365.25)
        af=smooth(a.rf,a.n,RUN_PRIOR); aa=smooth(a.ra,a.n,RUN_PRIOR); hf=smooth(h.rf,h.n,RUN_PRIOR); ha=smooth(h.ra,h.n,RUN_PRIOR)
        run_X.extend([[af,ha,a.ewm_rf,h.ewm_ra,lg_run,0.0,rest(a,d),float(a.n),ms,mc],[hf,aa,h.ewm_rf,a.ewm_ra,lg_run,1.0,rest(h,d),float(h.n),ms,mc]])
        run_y.extend([g['away_runs'],g['home_runs']]); run_year.extend([g['year'],g['year']]); run_gid.extend([g['game_pk'],g['game_pk']]); run_side.extend(['away','home'])
        aff=smooth(a.fi_for,a.n,FI_PRIOR); afa=smooth(a.fi_against,a.n,FI_PRIOR); hff=smooth(h.fi_for,h.n,FI_PRIOR); hfa=smooth(h.fi_against,h.n,FI_PRIOR)
        fi_X.append([aff,hff,hfa,afa,a.ewm_fi_for,h.ewm_fi_for,h.ewm_fi_against,a.ewm_fi_against,af,hf,ha,aa,lg_fi,rest(a,d),rest(h,d),ms,mc])
        fi_y.append(int(g['away_fi']+g['home_fi']>0)); fi_year.append(g['year']); fi_gid.append(g['game_pk'])
        ar,hr=g['away_runs'],g['home_runs']; ae=int(g['away_fi']>0); he=int(g['home_fi']>0)
        for st,rf,ra,ff,fa in ((a,ar,hr,ae,he),(h,hr,ar,he,ae)):
            st.n+=1; st.rf+=rf; st.ra+=ra; st.fi_for+=ff; st.fi_against+=fa
            st.ewm_rf=.94*st.ewm_rf+.06*rf; st.ewm_ra=.94*st.ewm_ra+.06*ra; st.ewm_fi_for=.94*st.ewm_fi_for+.06*ff; st.ewm_fi_against=.94*st.ewm_fi_against+.06*fa; st.last_date=d
        league_n+=1; league_runs+=ar+hr; league_fi_events+=ae+he
    return {k:np.asarray(v) for k,v in {'run_X':run_X,'run_y':run_y,'run_year':run_year,'run_gid':run_gid,'run_side':run_side,'fi_X':fi_X,'fi_y':fi_y,'fi_year':fi_year,'fi_gid':fi_gid}.items()}


def logit(p):
    p=np.clip(p,1e-6,1-1e-6); return np.log(p/(1-p))


def nb_draw(rng,mu,alpha,n):
    if alpha<=1e-12:return rng.poisson(mu,size=n)
    lam=rng.gamma(shape=1/alpha,scale=alpha*mu,size=n); return rng.poisson(lam)


def game_probs(mu_a,mu_h,alpha,sigma,n,seed):
    rng=np.random.default_rng(seed); shared=rng.lognormal(-.5*sigma*sigma,sigma,n) if sigma>0 else np.ones(n)
    a=nb_draw(rng,mu_a*shared,alpha,n); h=nb_draw(rng,mu_h*shared,alpha,n); return h,a,h-a,h+a


def metric(p,y):
    p=np.asarray(p,float);y=np.asarray(y,float); n=len(y); pred=float(p.mean()); act=float(y.mean()); se=math.sqrt(max(act*(1-act),1e-9)/n); z=abs(pred-act)/se
    return {'n':n,'pred':pred,'actual':act,'gap_pp':100*(pred-act),'z':z,'brier':float(np.mean((p-y)**2))}


def score_distribution(mu_a,mu_h,years,gids,actual_a,actual_h,alpha,sigma,n_sims):
    rows=[]
    for ma,mh,yr,gid,aa,hh in zip(mu_a,mu_h,years,gids,actual_a,actual_h):
        h,a,m,t=game_probs(float(ma),float(mh),alpha,sigma,n_sims,99173+int(gid)%100000)
        rows.append({'year':int(yr),'gid':int(gid),'home_ml':float(np.mean(h>a)+.5*np.mean(h==a)),'actual_home_ml':float(hh>aa)+.5*float(hh==aa),**{f'rl_{ln:+.1f}':float(np.mean(m+ln>0)) for ln in (-2.5,-1.5,1.5,2.5)},**{f'actual_rl_{ln:+.1f}':float((hh-aa)+ln>0) for ln in (-2.5,-1.5,1.5,2.5)},**{f'over_{ln:.1f}':float(np.mean(t>ln)) for ln in (7.5,8.5,9.5,10.5)},**{f'actual_over_{ln:.1f}':float((hh+aa)>ln) for ln in (7.5,8.5,9.5,10.5)}})
    return rows


def loss(rows):
    keys=['home_ml']+[f'rl_{x:+.1f}' for x in (-2.5,-1.5,1.5,2.5)]+[f'over_{x:.1f}' for x in (7.5,8.5,9.5,10.5)]
    return sum((np.mean([r[k] for r in rows])-np.mean([r['actual_'+k] for r in rows]))**2 for k in keys)


def report_rows(rows):
    keys=['home_ml']+[f'rl_{x:+.1f}' for x in (-2.5,-1.5,1.5,2.5)]+[f'over_{x:.1f}' for x in (7.5,8.5,9.5,10.5)]
    return {k:metric([r[k] for r in rows],[r['actual_'+k] for r in rows]) for k in keys}


def main():
    root=Path(os.getenv('SPORTSEDGE_GAME_REBUILD_CACHE','.cache/sportsedge/game-rebuild')); games=fetch_games(root/'schedule'); f=build_features(games)
    ry=f['run_year'].astype(int); train=ry<=2023; cal=ry==2024; hold=ry==2025
    run_model=HistGradientBoostingRegressor(loss='poisson',learning_rate=.045,max_iter=250,max_leaf_nodes=15,min_samples_leaf=80,l2_regularization=2.0,random_state=31); run_model.fit(f['run_X'][train],f['run_y'][train]); pred=run_model.predict(f['run_X'])
    sides=f['run_side'].astype(str); scale_a=float(f['run_y'][cal & (sides=='away')].sum()/pred[cal & (sides=='away')].sum()); scale_h=float(f['run_y'][cal & (sides=='home')].sum()/pred[cal & (sides=='home')].sum()); scaled=pred*np.where(sides=='home',scale_h,scale_a)
    def arrays(mask_year):
        gids=[];ma=[];mh=[];aa=[];hh=[];yrs=[];by={}
        for i,gid in enumerate(f['run_gid'].astype(int)):
            if not mask_year[i]:continue
            by.setdefault(gid,{})[sides[i]]=(scaled[i],f['run_y'][i],ry[i])
        for gid,v in by.items():
            if 'away' not in v or 'home' not in v:continue
            gids.append(gid);ma.append(v['away'][0]);mh.append(v['home'][0]);aa.append(v['away'][1]);hh.append(v['home'][1]);yrs.append(v['home'][2])
        return np.array(ma),np.array(mh),np.array(yrs),np.array(gids),np.array(aa),np.array(hh)
    calarr=arrays(cal); holdarr=arrays(hold); grid=[]
    for alpha in (0.10,0.18,0.26,0.34,0.42):
        for sigma in (0.0,0.08,0.16,0.24):
            rows=score_distribution(*calarr,alpha,sigma,800); grid.append((loss(rows),alpha,sigma))
    grid.sort();_,alpha,sigma=grid[0]; cal_rows=score_distribution(*calarr,alpha,sigma,4000); hold_rows=score_distribution(*holdarr,alpha,sigma,6000)
    game_report={'calibration_2024':report_rows(cal_rows),'final_holdout_2025':report_rows(hold_rows),'selected_on_2024':{'alpha':alpha,'shared_sigma':sigma,'away_scale':scale_a,'home_scale':scale_h},'n_games':len(games)}
    fy=f['fi_year'].astype(int); ft=fy<=2023; fc=fy==2024; fh=fy==2025
    fi_model=HistGradientBoostingClassifier(learning_rate=.04,max_iter=220,max_leaf_nodes=15,min_samples_leaf=100,l2_regularization=3.0,random_state=41); fi_model.fit(f['fi_X'][ft],f['fi_y'][ft]); raw=fi_model.predict_proba(f['fi_X'])[:,1]
    platt=LogisticRegression(C=100.0,solver='lbfgs').fit(logit(raw[fc]).reshape(-1,1),f['fi_y'][fc]); pcal=platt.predict_proba(logit(raw).reshape(-1,1))[:,1]
    fi_report={'calibration_2024':metric(pcal[fc],f['fi_y'][fc]),'final_holdout_2025':metric(pcal[fh],f['fi_y'][fh])}; buckets=[]; ph=pcal[fh]; yh=f['fi_y'][fh]
    for lo,hi in ((0,.2),(.2,.4),(.4,.6),(.6,.8),(.8,1.000001)):
        m=(ph>=lo)&(ph<hi)
        if m.sum()>=30:buckets.append({'lo':lo,'hi':hi,**metric(ph[m],yh[m])})
    fi_report['holdout_buckets']=buckets
    game_hold=game_report['final_holdout_2025']; ml_pass=game_hold['home_ml']['z']<=2.5; rl_pass=max(game_hold[k]['z'] for k in game_hold if k.startswith('rl_'))<=2.5; total_pass=max(game_hold[k]['z'] for k in game_hold if k.startswith('over_'))<=2.5; nrfi_pass=fi_report['final_holdout_2025']['z']<=2.5 and max([b['z'] for b in buckets] or [0])<=3.0
    validation={'schema_version':'core_game_markets_rebuild_v1','source':'MLB_STATSAPI_ONLY_NO_SPORTSBOOK_FEATURES','train':'2021-2023','calibration':'2024','final_holdout':'2025','markets':{'MONEYLINE':{'pass':ml_pass,'metrics':game_hold['home_ml']},'RUN_LINE':{'pass':rl_pass,'metrics':{k:v for k,v in game_hold.items() if k.startswith('rl_')}},'TOTALS':{'pass':total_pass,'metrics':{k:v for k,v in game_hold.items() if k.startswith('over_')}},'NRFI_YRFI':{'pass':nrfi_pass,'metrics':fi_report}},'game_report':game_report}
    art=Path('artifacts');art.mkdir(exist_ok=True); joblib.dump({'version':'GAME_SCORE_V2','run_model':run_model,'run_features':RUN_FEATURES,'away_scale':scale_a,'home_scale':scale_h,'alpha':alpha,'shared_sigma':sigma,'feature_policy':'prior_only_team_history'},art/'sportsedge_game_score_v2.joblib'); joblib.dump({'version':'NRFI_V2','model':fi_model,'calibrator':platt,'features':FI_FEATURES,'feature_policy':'prior_only_team_first_inning_history'},art/'sportsedge_nrfi_v2.joblib'); (art/'core_game_markets_validation.json').write_text(json.dumps(validation,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'games':len(games),'selected':validation['game_report']['selected_on_2024'],'passes':{k:v['pass'] for k,v in validation['markets'].items()}},indent=2)); return 0 if all(v['pass'] for v in validation['markets'].values()) else 2

if __name__=='__main__':raise SystemExit(main())
