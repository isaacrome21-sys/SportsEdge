#!/usr/bin/env python3
"""Rebuild pitcher-walk threshold models from official MLB boxscores.

Fixed protocol: train 2021-23, Platt-calibrate on 2024, final untouched 2025.
Feature definitions are explicit and prior-only; no sportsbook data is fetched.
"""
from __future__ import annotations
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
import calendar,json,math,os,time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen
import joblib,numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression

BASE='https://statsapi.mlb.com'; YEARS=(2021,2022,2023,2024,2025); THRESHOLDS=(0.5,1.5,2.5,3.5)
FEATURES=('pit_bb_hist','pit_er_hist','pit_h_hist','bf_mean','prior_starts','opp_bb_hist','opp_r_hist','opp_h_hist','lg_p_w','lg_p_er','month','sin_doy','cos_doy')
PITCHER_PRIOR_BF=100.; TEAM_PRIOR_PA=500.; PRIOR_W=.08; PRIOR_ER=.11; PRIOR_H=.22; PRIOR_R=.115
@dataclass
class PState: starts:int=0; bf:float=0; bb:float=0; er:float=0; hits:float=0
@dataclass
class TState: pa:float=0; bb:float=0; runs:float=0; hits:float=0

def get(path,params=None,retries=4):
 q=('?'+urlencode(params)) if params else '';u=BASE+path+q
 for a in range(retries):
  try:
   with urlopen(Request(u,headers={'Accept':'application/json'}),timeout=45) as r:return json.loads(r.read().decode())
  except Exception:
   if a+1==retries:raise
   time.sleep(.5*(2**a))

def month_ranges(y):
 for m in range(3,11):yield f'{y}-{m:02d}-01',f'{y}-{m:02d}-{calendar.monthrange(y,m)[1]:02d}'

def fetch_schedule(cache):
 cache.mkdir(parents=True,exist_ok=True); by={}
 for y in YEARS:
  for s,e in month_ranges(y):
   p=cache/f'schedule_{s}_{e}.json'
   if p.exists():d=json.loads(p.read_text())
   else:d=get('/api/v1/schedule',{'sportId':1,'startDate':s,'endDate':e,'hydrate':'team'});p.write_text(json.dumps(d))
   for db in d.get('dates') or []:
    for g in db.get('games') or []:
     if g.get('gameType')!='R' or (g.get('status') or {}).get('abstractGameState')!='Final':continue
     try:dt=date.fromisoformat(str(g.get('officialDate') or db.get('date'))); aid=int(g['teams']['away']['team']['id']);hid=int(g['teams']['home']['team']['id']);pk=int(g['gamePk'])
     except Exception:continue
     by[pk]={'game_pk':pk,'date':dt.isoformat(),'year':y,'away_id':aid,'home_id':hid}
 return sorted(by.values(),key=lambda x:(x['date'],x['game_pk']))

def load_box(pk,cache):
 p=cache/f'{pk}.json'
 if p.exists():return json.loads(p.read_text())
 d=get(f'/api/v1/game/{pk}/boxscore');p.write_text(json.dumps(d));return d

def ensure_boxes(games,cache):
 cache.mkdir(parents=True,exist_ok=True);todo=[g['game_pk'] for g in games if not (cache/f"{g['game_pk']}.json").exists()]
 print(json.dumps({'boxscores_total':len(games),'boxscores_to_fetch':len(todo)}))
 with ThreadPoolExecutor(max_workers=18) as ex:
  fut={ex.submit(load_box,pk,cache):pk for pk in todo}
  for i,f in enumerate(as_completed(fut),1):
   try:f.result()
   except Exception as e:print('BOX_FAIL',fut[f],type(e).__name__,str(e)[:120])
   if i%500==0:print('BOX_PROGRESS',i,len(todo))

def starter(team):
 players=team.get('players') or {}
 for pid in team.get('pitchers') or []:
  rec=players.get('ID'+str(pid)) or {}; st=(rec.get('stats') or {}).get('pitching') or {}
  if int(st.get('gamesStarted') or 0)==1:
   return int(pid),st
 return None,None

def safe(st,k):
 try:return float(st.get(k) or 0)
 except:return 0.
def rate(num,den,prior,prior_den):return (num+prior*prior_den)/(den+prior_den)
def logit(p):p=np.clip(p,1e-6,1-1e-6);return np.log(p/(1-p))
def metric(p,y):
 p=np.asarray(p,float);y=np.asarray(y,float);n=len(y);pm=float(p.mean());am=float(y.mean());se=math.sqrt(max(am*(1-am),1e-9)/n);return {'n':n,'pred':pm,'actual':am,'gap_pp':100*(pm-am),'z':abs(pm-am)/se,'brier':float(np.mean((p-y)**2))}

def build(games,boxdir):
 ps=defaultdict(PState);ts=defaultdict(TState);lg_bf=lg_bb=lg_er=0.;X=[];walks=[];years=[];ids=[]
 for g in games:
  p=boxdir/f"{g['game_pk']}.json"
  if not p.exists():continue
  try:box=json.loads(p.read_text())
  except:continue
  teams=box.get('teams') or {}; d=date.fromisoformat(g['date']);doy=d.timetuple().tm_yday;sw=math.sin(2*math.pi*doy/365.25);cw=math.cos(2*math.pi*doy/365.25)
  lpw=(lg_bb+PRIOR_W*12000)/(lg_bf+12000);lper=(lg_er+PRIOR_ER*12000)/(lg_bf+12000)
  updates=[]
  for side,opp_side,tid,opp_tid in [('away','home',g['away_id'],g['home_id']),('home','away',g['home_id'],g['away_id'])]:
   team=teams.get(side) or {}; pid,st=starter(team)
   if pid is None or st is None:continue
   bf=safe(st,'battersFaced');bb=safe(st,'baseOnBalls');er=safe(st,'earnedRuns');hh=safe(st,'hits')
   if bf<=0:continue
   q=ps[pid];o=ts[opp_tid]
   feats=[rate(q.bb,q.bf,lpw,PITCHER_PRIOR_BF),rate(q.er,q.bf,lper,PITCHER_PRIOR_BF),rate(q.hits,q.bf,PRIOR_H,PITCHER_PRIOR_BF),(q.bf/q.starts if q.starts else 22.0),float(q.starts),rate(o.bb,o.pa,PRIOR_W,TEAM_PRIOR_PA),rate(o.runs,o.pa,PRIOR_R,TEAM_PRIOR_PA),rate(o.hits,o.pa,PRIOR_H,TEAM_PRIOR_PA),lpw,lper,float(d.month),sw,cw]
   X.append(feats);walks.append(bb);years.append(g['year']);ids.append((g['game_pk'],pid,opp_tid));updates.append((pid,bf,bb,er,hh))
  for side,tid in [('away',g['away_id']),('home',g['home_id'])]:
   bat=((teams.get(side) or {}).get('teamStats') or {}).get('batting') or {};t=ts[tid];t.pa+=safe(bat,'plateAppearances');t.bb+=safe(bat,'baseOnBalls');t.runs+=safe(bat,'runs');t.hits+=safe(bat,'hits')
  for pid,bf,bb,er,hh in updates:
   q=ps[pid];q.starts+=1;q.bf+=bf;q.bb+=bb;q.er+=er;q.hits+=hh;lg_bf+=bf;lg_bb+=bb;lg_er+=er
 return np.asarray(X,float),np.asarray(walks,float),np.asarray(years,int),ids

def main():
 root=Path(os.getenv('SPORTSEDGE_BB_REBUILD_CACHE','.cache/sportsedge/bb-rebuild'));games=fetch_schedule(root/'schedule');ensure_boxes(games,root/'boxscores');X,w,yr,ids=build(games,root/'boxscores')
 train=yr<=2023;cal=yr==2024;hold=yr==2025;artmodels={};report={};allpass=True
 for ln in THRESHOLDS:
  y=(w>ln).astype(int);m=HistGradientBoostingClassifier(learning_rate=.045,max_iter=250,max_leaf_nodes=15,min_samples_leaf=100,l2_regularization=3.,random_state=19);m.fit(X[train],y[train]);raw=m.predict_proba(X)[:,1]
  c=LogisticRegression(C=100.,solver='lbfgs').fit(logit(raw[cal]).reshape(-1,1),y[cal]);p=c.predict_proba(logit(raw).reshape(-1,1))[:,1]
  hm=metric(p[hold],y[hold]);cm=metric(p[cal],y[cal]);buckets=[];ph=p[hold];yh=y[hold]
  for lo,hi in ((0,.2),(.2,.4),(.4,.6),(.6,.8),(.8,1.000001)):
   z=(ph>=lo)&(ph<hi)
   if z.sum()>=30:buckets.append({'lo':lo,'hi':hi,**metric(ph[z],yh[z])})
  passed=hm['z']<=2.5 and max([b['z'] for b in buckets] or [0])<=3.0;allpass &= passed;report[str(ln)]={'pass':passed,'calibration_2024':cm,'final_holdout_2025':hm,'holdout_buckets':buckets};artmodels[str(ln)]={'model':m,'calibrator':c}
 metadata={'version':'PITCHER_BB_V3','source':'MLB_STATSAPI_BOXSCORING_ONLY','train':'2021-2023','calibration':'2024','final_holdout':'2025','features':FEATURES,'definitions':{'pit_bb_hist':'smoothed prior starter BB/battersFaced','pit_er_hist':'smoothed prior starter ER/battersFaced','pit_h_hist':'smoothed prior starter H/battersFaced','bf_mean':'prior mean battersFaced per start','prior_starts':'prior MLB starts observed','opp_bb_hist':'smoothed opponent team batting BB/PA','opp_r_hist':'smoothed opponent team runs/PA','opp_h_hist':'smoothed opponent team hits/PA','lg_p_w':'prior-date league starter BB/BF','lg_p_er':'prior-date league starter ER/BF','month':'calendar month','sin_doy':'sin day-of-year','cos_doy':'cos day-of-year'},'threshold_report':report,'all_thresholds_pass':bool(allpass),'rows':int(len(X))}
 Path('artifacts').mkdir(exist_ok=True);joblib.dump({'metadata':metadata,'models':artmodels},'artifacts/sportsedge_pitcher_bb_v3.joblib');Path('artifacts/pitcher_bb_v3_validation.json').write_text(json.dumps(metadata,indent=2,sort_keys=True)+'\n');print(json.dumps({'rows':len(X),'holdout':int(hold.sum()),'passes':{k:v['pass'] for k,v in report.items()}},indent=2));return 0 if allpass else 2
if __name__=='__main__':raise SystemExit(main())
