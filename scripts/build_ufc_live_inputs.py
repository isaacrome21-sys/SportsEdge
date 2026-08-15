#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,json,re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.request import Request,urlopen
from sportsedge.ufc_source import upcoming_event_urls,parse_event,fighter_urls_from_bout,parse_fighter_profile
from sportsedge.ufc_training import update_elo

DATA_URL='https://raw.githubusercontent.com/rfordatascience/tidytuesday/main/data/2026/2026-07-07/ultimate_ufc_dataset.csv'

def _f(r,k,d=0.0):
    try:return float(r.get(k) or d)
    except:return d

def _age(dob,event_date):
    if not dob:return 30.0
    for fmt in ('%b %d, %Y','%B %d, %Y'):
        try:
            d=datetime.strptime(dob,fmt); e=datetime.strptime(event_date,'%B %d, %Y')
            return (e-d).days/365.2425
        except:pass
    return 30.0

def _history():
    req=Request(DATA_URL,headers={'User-Agent':'SportsEdge/1.0'})
    text=urlopen(req,timeout=60).read().decode('utf-8')
    rows=list(csv.DictReader(text.splitlines())); rows=[r for r in rows if r.get('winner') in {'Red','Blue'} and r.get('date')]
    rows.sort(key=lambda r:r['date']); latest={}; last_date={}; elo=defaultdict(lambda:1500.0)
    for r in rows:
        rn,bn=r['r_fighter'],r['b_fighter']; er,eb=elo[rn],elo[bn]; y=1.0 if r['winner']=='Red' else 0.0
        for side,name in [('r',rn),('b',bn)]: latest[name]=(side,r); last_date[name]=r['date']
        elo[rn],elo[bn]=update_elo(er,eb,y)
    return latest,last_date,elo

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--fighters',default='data/ufc/fighters_today.json');ap.add_argument('--contexts',default='data/ufc/contexts_today.json');a=ap.parse_args()
    urls=upcoming_event_urls()
    if not urls: raise SystemExit('UFC_UPCOMING_EVENT_MISSING')
    bouts=parse_event(urls[0]);
    if not bouts: raise SystemExit('UFC_UPCOMING_BOUTS_MISSING')
    latest,last_date,elo=_history(); fighters={}; contexts=[]
    for i,b in enumerate(bouts):
        try: ua,ub=fighter_urls_from_bout(b.bout_url); pa,pb=parse_fighter_profile(ua),parse_fighter_profile(ub)
        except Exception as exc:
            print('snapshot skip',b.fighter_a,b.fighter_b,exc); continue
        for p in (pa,pb):
            side,row=latest.get(p.name,('',{})); wins=int(_f(row,f'{side}_wins',0)); losses=int(_f(row,f'{side}_losses',0))
            finish_wins=_f(row,f'{side}_win_by_ko_tko')+_f(row,f'{side}_win_by_submission')
            rw=min(1.0,max(0.0,0.5+0.08*(_f(row,f'{side}_current_win_streak')-_f(row,f'{side}_current_lose_streak')))) if side else 0.5
            height=p.height_in or 0.0; reach=p.reach_in or 0.0; missing=sum(x==0.0 for x in (height,reach,p.slpm,p.sapm))/4.0
            days=180.0
            if p.name in last_date:
                try: days=max(0.0,(datetime.strptime(b.event_date,'%B %d, %Y')-datetime.strptime(last_date[p.name],'%Y-%m-%d')).days)
                except: pass
            fighters[p.name]={'name':p.name,'age':_age(p.dob,b.event_date),'height_in':height,'reach_in':reach,'stance':p.stance or 'Unknown','wins':wins,'losses':losses,'draws':0,
              'sig_strikes_landed_pm':p.slpm,'sig_strikes_absorbed_pm':p.sapm,'sig_strike_accuracy':p.str_acc,'sig_strike_defense':p.str_def,
              'takedowns_per_15':p.td_avg,'takedown_accuracy':p.td_acc,'takedown_defense':p.td_def,'submissions_per_15':p.sub_avg,'control_seconds_per_15':0.0,'knockdowns_per_15':0.0,
              'finish_win_rate':(finish_wins/wins if wins else 0.0),'finish_loss_rate':0.0,'recent_win_rate':rw,'strength_of_schedule':0.5,'elo':elo[p.name],'days_since_last_fight':days,
              'weight_class':b.weight_class,'late_replacement':False,'missingness':missing}
        title = i < 2 and ('330' in b.event or 'title' in b.weight_class.lower())
        rounds=5 if title or i<2 else 3
        contexts.append({'fighter_a':b.fighter_a,'fighter_b':b.fighter_b,'rounds':rounds,'title_fight':bool(title),'short_notice_days':None,'altitude_ft':0.0})
    Path(a.fighters).parent.mkdir(parents=True,exist_ok=True);Path(a.contexts).parent.mkdir(parents=True,exist_ok=True)
    Path(a.fighters).write_text(json.dumps({'event':bouts[0].event,'event_date':bouts[0].event_date,'fighters':list(fighters.values())},indent=2,sort_keys=True))
    Path(a.contexts).write_text(json.dumps(contexts,indent=2,sort_keys=True))
    print(json.dumps({'event':bouts[0].event,'fighters':len(fighters),'bouts':len(contexts)},sort_keys=True))
if __name__=='__main__':main()
