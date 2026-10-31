"""Research-only NFL props pricer: repo's Part 2 evaluator math (mu shrinkage K=3, pooled CV
trained 2018-19, gamma/NB CDF) + engines_v1 families, run on current nflverse data incl 2026.
Scratch paths; method record, not a repo tool. NOT the frozen Part 2 pricer.
Usage: python price.py lines.csv out.json   (csv: player,market,line,over,under)"""
import sys,csv,json,gzip,importlib.util,math
from pathlib import Path
import numpy as np
SE=Path('/home/claude/se'); sys.path.insert(0,str(SE))
P2=SE/'research/nfl_props_part2_20261018'
spec=importlib.util.spec_from_file_location('ev',P2/'eval_nfl_props_calibration_v1.py');ev=importlib.util.module_from_spec(spec);spec.loader.exec_module(ev)
spec=importlib.util.spec_from_file_location('pr',P2/'price_nfl_props_part2.py');pr=importlib.util.module_from_spec(spec);spec.loader.exec_module(pr)
from sportsedge import nfl_prop_engines_v1 as e1
D=Path('/home/claude/nflp')
data=ev.load(D); data1=e1.load_player_data(D)
names={}
for f in sorted(D.glob('sp_2026*.csv.gz')):
    for r in csv.DictReader(gzip.open(f,'rt')): names[r['player_display_name'].lower()]=r['player_id']
cvs={m:pr.train_cv(ev,data,cfg) for m,cfg in ev.MARKETS.items()}
built={};pools={}
grid=np.arange(ev.GRID_LO,ev.GRID_HI+1,dtype=float)
ALIAS={'pass yds':'PASS_YDS','passing yards':'PASS_YDS','rush yds':'RUSH_YDS','rushing yards':'RUSH_YDS','rec yds':'REC_YDS','receiving yards':'REC_YDS','receptions':'RECEPTIONS',
 'pass+rush yds':'pass_plus_rush_yards','rush+rec yds':'rush_plus_rec_yards','targets':'targets','sacks':'player_sacks','tackles+assists':'tackles_assists','interceptions (def)':'player_interceptions','fg made':'fg_made','kicking points':'kicking_points','xp made':'xp_made'}
# Calibration shifts from RESEARCH_RECORD.md section 3 (receptions -0.04 failed 2026 holdout, dropped)
CAL={'PASS_YDS':0.05,'RUSH_YDS':0.04,'REC_YDS':0.0,'RECEPTIONS':0.0,'pass_plus_rush_yards':0.03,'rush_plus_rec_yards':0.01,'targets':-0.035,'tackles_assists':-0.025}
dec=lambda a:1+(a/100 if a>0 else 100/-a)
def run(lines_csv,season=2026,week=8):
    out=[]
    for r in csv.DictReader(open(lines_csv)):
        pid=names.get(r['player'].strip().lower()); mk=ALIAS.get(r['market'].strip().lower(),r['market'].strip())
        line=float(r['line']);o=int(r['over']);u=int(r['under'])
        base=dict(player=r['player'],market=mk,line=line,over=o,under=u)
        if not pid: out.append({**base,'status':'UNKNOWN_PLAYER'});continue
        if mk in ev.MARKETS:
            try:
                res=pr._price_one_row(ev,data,season,week,dict(game_id='g',player_id=pid,market=mk,line=line,over_price=o,under_price=u,captured_at='2026-10-31T12:00:00+00:00',kickoff='2026-11-01T18:00:00+00:00'),cvs,grid,built,pools)
            except Exception as ex: out.append({**base,'status':f'ERR {ex}'});continue
            if res.get('status')!='PRICED': out.append({**base,'status':res.get('reason') or res.get('refusal_reason') or res.get('status')});continue
            po=res['p_over']; mu=res.get('mu')
            po=min(0.97,max(0.03,po+CAL.get(mk,0.0)))
        elif mk in e1.FAMILIES:
            res=e1.price_nfl_prop(mk,pid,line,data1,season,week)
            if res['status']!='PRICED': out.append({**base,'status':res['reason']});continue
            po=res['p_over']; mu=res['mu']
            po=min(0.97,max(0.03,po+CAL.get(mk,0.0)))
        else: out.append({**base,'status':'NO_ENGINE'});continue
        evo=po*dec(o)-1; evu=(1-po)*dec(u)-1
        side,evx,p=('Over',evo,po) if evo>evu else ('Under',evu,1-po)
        out.append({**base,'status':'PRICED','mu':mu,'p_over':po,'pick':side,'p':p,'ev':evx})
    return out
if __name__=='__main__':
    res=run(sys.argv[1]);json.dump(res,open(sys.argv[2],'w'),indent=1)
    for x in sorted([x for x in res if x['status']=='PRICED'],key=lambda x:-x['ev']):
        print(f"{x['ev']*100:+6.1f}% {x['player']:20} {x['market']:22} {x['pick']} {x['line']}  mu={x['mu']:.1f} p={x['p']:.2f}")
