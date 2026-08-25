#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,json,unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request,urlopen
from sportsedge.ufc_source import bout_rounds_from_detail,upcoming_event_urls,parse_event,fighter_urls_from_bout,parse_fighter_profile
from sportsedge.ufc_training import update_elo

DATA_URL='https://raw.githubusercontent.com/rfordatascience/tidytuesday/main/data/2026/2026-07-07/ultimate_ufc_dataset.csv'

def _f(r,k,d=0.0):
    try:return float(r.get(k) or d)
    except:return d

def _norm(s):
    return ''.join(c for c in unicodedata.normalize('NFKD',str(s or '')) if not unicodedata.combining(c)).lower().replace("'",'').replace('-',' ').strip()

def _history():
    req=Request(DATA_URL,headers={'User-Agent':'SportsEdge/1.0'})
    text=urlopen(req,timeout=60).read().decode('utf-8')
    rows=list(csv.DictReader(text.splitlines())); rows=[r for r in rows if r.get('winner') in {'Red','Blue'} and r.get('date')]
    rows.sort(key=lambda r:r['date']); latest={}; last_date={}; elo=defaultdict(lambda:1500.0)
    for r in rows:
        rn,bn=r['r_fighter'],r['b_fighter']; er,eb=elo[_norm(rn)],elo[_norm(bn)]; y=1.0 if r['winner']=='Red' else 0.0
        for side,name in [('r',rn),('b',bn)]: latest[_norm(name)]=(side,r); last_date[_norm(name)]=r['date']
        elo[_norm(rn)],elo[_norm(bn)]=update_elo(er,eb,y)
    return latest,last_date,elo

def _event_dt(text):
    for fmt in ('%B %d, %Y','%b %d, %Y','%Y-%m-%d'):
        try:return datetime.strptime(text,fmt)
        except:pass
    raise ValueError('UFC_EVENT_DATE_INVALID')

def _age_from_dob(dob,event_date):
    if not dob:return None
    birth=None
    for fmt in ('%b %d, %Y','%B %d, %Y','%Y-%m-%d'):
        try:birth=datetime.strptime(dob,fmt);break
        except:pass
    if birth is None:return None
    event=_event_dt(event_date)
    return max(18.0,(event-birth).days/365.2425)

def _snapshot_from_history(name, weight_class, event_date, latest,last_date,elo, *, late_replacement=False):
    key=_norm(name); side,row=latest.get(key,('',{})); event_dt=_event_dt(event_date)
    if not side:
        return {'name':name,'age':30.0,'height_in':0.0,'reach_in':0.0,'stance':'Unknown','wins':0,'losses':0,'draws':0,
          'sig_strikes_landed_pm':0.0,'sig_strikes_absorbed_pm':0.0,'sig_strike_accuracy':0.0,'sig_strike_defense':0.0,
          'takedowns_per_15':0.0,'takedown_accuracy':0.0,'takedown_defense':0.0,'submissions_per_15':0.0,'control_seconds_per_15':0.0,'knockdowns_per_15':0.0,
          'finish_win_rate':0.0,'finish_loss_rate':0.0,'recent_win_rate':0.5,'strength_of_schedule':0.5,'elo':elo[key],
          'days_since_last_fight':180.0,'weight_class':weight_class,'late_replacement':late_replacement,'missingness':1.0}
    last_dt=datetime.strptime(last_date[key],'%Y-%m-%d'); days=max(0,(event_dt-last_dt).days)
    hist_age=_f(row,f'{side}_age',30.0); age=hist_age + days/365.2425
    height=_f(row,f'{side}_height_cms')/2.54; reach=_f(row,f'{side}_reach_cms')/2.54
    slpm=_f(row,f'{side}_avg_sig_str_landed'); stracc=_f(row,f'{side}_avg_sig_str_pct'); tdavg=_f(row,f'{side}_avg_td_landed'); tdacc=_f(row,f'{side}_avg_td_pct'); subavg=_f(row,f'{side}_avg_sub_att')
    wins=int(_f(row,f'{side}_wins')); losses=int(_f(row,f'{side}_losses'))
    finish_wins=_f(row,f'{side}_win_by_ko_tko')+_f(row,f'{side}_win_by_submission')
    rw=min(1.0,max(0.0,0.5+0.08*(_f(row,f'{side}_current_win_streak')-_f(row,f'{side}_current_lose_streak'))))
    core=(height,reach,slpm,stracc,tdavg,tdacc,subavg); missing=sum(x==0.0 for x in core)/len(core)
    return {'name':name,'age':age,'height_in':height,'reach_in':reach,'stance':str(row.get(f'{side}_stance') or 'Unknown'),'wins':wins,'losses':losses,'draws':0,
      'sig_strikes_landed_pm':slpm,'sig_strikes_absorbed_pm':0.0,'sig_strike_accuracy':stracc,'sig_strike_defense':0.0,
      'takedowns_per_15':tdavg,'takedown_accuracy':tdacc,'takedown_defense':0.0,'submissions_per_15':subavg,'control_seconds_per_15':0.0,'knockdowns_per_15':0.0,
      'finish_win_rate':(finish_wins/wins if wins else 0.0),'finish_loss_rate':0.0,'recent_win_rate':rw,'strength_of_schedule':0.5,'elo':elo[key],
      'days_since_last_fight':float(days),'weight_class':weight_class,'late_replacement':late_replacement,'missingness':min(1.0,missing+0.15)}

def _from_override(path, latest,last_date,elo):
    cfg=json.loads(Path(path).read_text()); fighters={}; contexts=[]
    event_day=_event_dt(cfg['event_date']).date(); today=datetime.now(timezone.utc).date()
    if abs((today-event_day).days)>1:
        raise SystemExit(f'UFC_OVERRIDE_DATE_MISMATCH event_date={event_day.isoformat()} utc_today={today.isoformat()}')
    for b in cfg['bouts']:
        late=str(b.get('late_replacement') or '')
        for name in (b['fighter_a'],b['fighter_b']):
            fighters[name]=_snapshot_from_history(name,b.get('weight_class',''),cfg['event_date'],latest,last_date,elo,late_replacement=(name==late))
        contexts.append({'fighter_a':b['fighter_a'],'fighter_b':b['fighter_b'],'rounds':int(b.get('rounds',3)),'title_fight':bool(b.get('title_fight',False)),
                         'short_notice_days':b.get('short_notice_days'),'altitude_ft':0.0})
    return cfg['event'],cfg['event_date'],fighters,contexts

def _from_ufcstats(latest,last_date,elo):
    urls=upcoming_event_urls()
    if not urls:return None
    bouts=parse_event(urls[0])
    if not bouts:return None
    fighters={}; contexts=[]
    for b in bouts:
        try:
            ua,ub=fighter_urls_from_bout(b.bout_url)
            rounds=bout_rounds_from_detail(b.bout_url)
            pa,pb=parse_fighter_profile(ua),parse_fighter_profile(ub)
        except Exception:
            continue
        for p in (pa,pb):
            snap=_snapshot_from_history(p.name,b.weight_class,b.event_date,latest,last_date,elo)
            age=_age_from_dob(p.dob,b.event_date)
            snap.update({'age':age or snap['age'],'height_in':p.height_in or snap['height_in'],'reach_in':p.reach_in or snap['reach_in'],'stance':p.stance or snap['stance'],
                         'sig_strikes_landed_pm':p.slpm or snap['sig_strikes_landed_pm'],'sig_strikes_absorbed_pm':p.sapm,
                         'sig_strike_accuracy':p.str_acc or snap['sig_strike_accuracy'],'sig_strike_defense':p.str_def,
                         'takedowns_per_15':p.td_avg or snap['takedowns_per_15'],'takedown_accuracy':p.td_acc or snap['takedown_accuracy'],
                         'takedown_defense':p.td_def,'submissions_per_15':p.sub_avg or snap['submissions_per_15']})
            fighters[p.name]=snap
        title='title' in b.weight_class.lower()
        contexts.append({'fighter_a':b.fighter_a,'fighter_b':b.fighter_b,'rounds':rounds,'title_fight':title,'short_notice_days':None,'altitude_ft':0.0})
    return bouts[0].event,bouts[0].event_date,fighters,contexts

def _validate_card(fighters, contexts):
    bouts=len(contexts); count=len(fighters)
    if bouts < 1:raise SystemExit('UFC_LIVE_INPUTS_INCOMPLETE fighters=0 bouts=0')
    expected=2*bouts
    if count != expected:raise SystemExit(f'UFC_LIVE_INPUTS_INCOMPLETE fighters={count} bouts={bouts} expected_fighters={expected}')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--fighters',default='data/ufc/fighters_today.json');ap.add_argument('--contexts',default='data/ufc/contexts_today.json');ap.add_argument('--override',default='');a=ap.parse_args()
    latest,last_date,elo=_history(); result=_from_ufcstats(latest,last_date,elo)
    if result is None:
        if not a.override or not Path(a.override).exists(): raise SystemExit('UFC_LIVE_INPUTS_UNAVAILABLE')
        result=_from_override(a.override,latest,last_date,elo)
    event,event_date,fighters,contexts=result; _validate_card(fighters,contexts)
    Path(a.fighters).parent.mkdir(parents=True,exist_ok=True);Path(a.contexts).parent.mkdir(parents=True,exist_ok=True)
    Path(a.fighters).write_text(json.dumps({'event':event,'event_date':event_date,'generated_at':datetime.now(timezone.utc).isoformat(),'fighters':list(fighters.values())},indent=2,sort_keys=True))
    Path(a.contexts).write_text(json.dumps(contexts,indent=2,sort_keys=True))
    print(json.dumps({'event':event,'fighters':len(fighters),'bouts':len(contexts),'max_missingness':max(x['missingness'] for x in fighters.values())},sort_keys=True))
if __name__=='__main__':main()
