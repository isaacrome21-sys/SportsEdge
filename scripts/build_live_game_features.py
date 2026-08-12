#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from datetime import date,timedelta,datetime,timezone
from pathlib import Path
from sportsedge.game_history_live import fetch_prior_finals
from sportsedge.game_live_features import new_history_state,apply_result,feature_one
from sportsedge.mlb_source import fetch_schedule

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--slate-date',required=True); ap.add_argument('--cache-dir',default='.cache/sportsedge/game-core-history'); ap.add_argument('--out',default='artifacts/live_game_features.json'); args=ap.parse_args()
    slate=date.fromisoformat(args.slate_date); prior=slate-timedelta(days=1)
    games,excluded=fetch_prior_finals(through_date=prior,cache_dir=args.cache_dir)
    state=new_history_state()
    i=0
    while i<len(games):
        day=games[i]['officialDate']; batch=[]
        while i<len(games) and games[i]['officialDate']==day: batch.append(games[i]); i+=1
        for g in batch: feature_one(state,g)
        for g in batch: apply_result(state,g)
    schedule=fetch_schedule(args.slate_date, now=datetime.now(timezone.utc))
    rows=[]
    for g in schedule:
        run_rows,fi_row=feature_one(state,{"game_pk":g.game_pk,"officialDate":g.official_date,"away_id":g.away_id,"home_id":g.home_id})
        rows.append({"game_id":str(g.game_pk),"game_pk":g.game_pk,"official_date":g.official_date,"away_id":g.away_id,"home_id":g.home_id,"run_rows":run_rows,"fi_row":fi_row,"history_cutoff":prior.isoformat()})
    out={"schema_version":"game_live_features_v1","slate_date":args.slate_date,"history_cutoff":prior.isoformat(),"history_games":len(games),"excluded_count":len(excluded),"game_count":len(rows),"games":rows}
    p=Path(args.out); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:out[k] for k in ('slate_date','history_cutoff','history_games','excluded_count','game_count')},indent=2))
if __name__=='__main__': main()
