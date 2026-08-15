#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,json
from collections import defaultdict
from pathlib import Path
from urllib.request import Request,urlopen
from sportsedge.ufc_training import TrainingRow,fit_chronological,update_elo

DEFAULT_URL='https://raw.githubusercontent.com/rfordatascience/tidytuesday/main/data/2026/2026-07-07/ultimate_ufc_dataset.csv'

def f(row,k,d=0.0):
    try:return float(row.get(k) or d)
    except:return d

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--url',default=DEFAULT_URL);ap.add_argument('--output',default='models/ufc_logistic_v1.json');ap.add_argument('--metrics',default='artifacts/ufc_training_metrics.json');a=ap.parse_args()
    req=Request(a.url,headers={'User-Agent':'SportsEdge/1.0'})
    text=urlopen(req,timeout=60).read().decode('utf-8')
    rows=list(csv.DictReader(text.splitlines()))
    rows=[r for r in rows if r.get('winner') in {'Red','Blue'} and r.get('date')]
    rows.sort(key=lambda r:(r['date'],r.get('r_fighter',''),r.get('b_fighter','')))
    elo=defaultdict(lambda:1500.0); out=[]
    for r in rows:
        rn,bn=r['r_fighter'],r['b_fighter']; er,eb=elo[rn],elo[bn]
        recent_r=min(1.0,max(0.0,0.5+0.08*(f(r,'r_current_win_streak')-f(r,'r_current_lose_streak'))))
        recent_b=min(1.0,max(0.0,0.5+0.08*(f(r,'b_current_win_streak')-f(r,'b_current_lose_streak'))))
        features={
          'elo_diff':er-eb,'age_diff':f(r,'r_age')-f(r,'b_age'),'reach_diff':(f(r,'r_reach_cms')-f(r,'b_reach_cms'))/2.54,
          'height_diff':(f(r,'r_height_cms')-f(r,'b_height_cms'))/2.54,'slpm_diff':f(r,'r_avg_sig_str_landed')-f(r,'b_avg_sig_str_landed'),
          'sapm_diff':0.0,'str_acc_diff':f(r,'r_avg_sig_str_pct')-f(r,'b_avg_sig_str_pct'),'str_def_diff':0.0,
          'td_avg_diff':f(r,'r_avg_td_landed')-f(r,'b_avg_td_landed'),'td_acc_diff':f(r,'r_avg_td_pct')-f(r,'b_avg_td_pct'),'td_def_diff':0.0,
          'sub_avg_diff':f(r,'r_avg_sub_att')-f(r,'b_avg_sub_att'),'recent_win_rate_diff':recent_r-recent_b,'sos_diff':0.0,'rest_days_diff':0.0,
          'late_replacement_diff':0.0,'experience_diff':(f(r,'r_wins')+f(r,'r_losses'))-(f(r,'b_wins')+f(r,'b_losses'))}
        y=1 if r['winner']=='Red' else 0
        out.append(TrainingRow(r['date'],r.get('location',''),rn,bn,y,features))
        elo[rn],elo[bn]=update_elo(er,eb,float(y))
    model,metrics=fit_chronological(out)
    Path(a.output).parent.mkdir(parents=True,exist_ok=True);Path(a.metrics).parent.mkdir(parents=True,exist_ok=True)
    payload=model.as_dict();payload['training_source']=a.url;payload['training_rows']=len(out);payload['last_training_fight_date']=rows[-1]['date'];payload['holdout_metrics']=metrics.__dict__
    Path(a.output).write_text(json.dumps(payload,indent=2,sort_keys=True))
    Path(a.metrics).write_text(json.dumps(metrics.__dict__,indent=2,sort_keys=True))
    print(json.dumps({'rows':len(out),'last_date':rows[-1]['date'],**metrics.__dict__},sort_keys=True))
if __name__=='__main__':main()
