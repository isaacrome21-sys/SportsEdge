#!/usr/bin/env python3
from datetime import datetime,timezone,timedelta
from live_feature_bridge_v0_2 import *
NOW=datetime(2026,8,10,22,tzinfo=timezone.utc); CUT=datetime(2026,8,10,23,5,tzinfo=timezone.utc); G='NYY_BOS_20260810'; E='p1'
MAP={'hr_rate':f'hr_rate:{G}:home:3','ob_rate':f'ob_rate:{G}:home:3','xb_rate':f'xb_rate:{G}:home:3','team_obp':f'team_obp:{G}:home:3','slot':f'slot:{G}:home:3'}
L={k:43200 for k in MAP}; SCH={'is_complete_day_snapshot':True,'expected_game_ids':[G]}; IDS={E}; CAPS={}
def mk(k,v,status='CONFIRMED',et=None,rt=None,sid=None,kind='MODEL_INPUT'):
 et=et or (NOW-timedelta(hours=1)).isoformat(); rt=rt or (NOW-timedelta(minutes=55)).isoformat()
 return SourceFact(sid or 's_'+k,k,v,'TEST',et,rt,status,kind,10)
def base():
 vals={'hr_rate':.04,'ob_rate':.34,'xb_rate':.09,'team_obp':.32,'slot':3}
 return [mk(MAP[k],v) for k,v in vals.items()]
def build(s=None,m=MAP,l=L,caps=CAPS,sch=SCH,ids=IDS): return build_model_input('rbi',E,G,m,s or base(),NOW,CUT,l,runtime_capabilities=caps,schedule_attestation=sch,known_entity_ids=ids)
mi,f=build(); assert mi and not f
m=dict(MAP);m.pop('slot'); mi,f=build(m=m); assert f.reason=='CONTRACT_MISMATCH'
m=dict(MAP);m['junk']=f'junk:{G}'; mi,f=build(m=m); assert f.reason=='CONTRACT_MISMATCH'
s=base();s[0]=mk(MAP['hr_rate'],.04,rt=(CUT+timedelta(seconds=1)).isoformat());mi,f=build(s=s);assert f.reason=='TEMPORAL_INVALID'
l=dict(L);l.pop('hr_rate');mi,f=build(l=l);assert f.reason=='MISSING_TTL'
s=base();s[-1]=mk(MAP['slot'],.1);mi,f=build(s=s);assert f.reason=='INVALID_FEATURE_VALUE'
mi,f=build(ids={'other'});assert f.reason=='UNKNOWN_ENTITY'
mi,f=build(sch={'is_complete_day_snapshot':False,'expected_game_ids':[G]});assert f.reason=='SCHEDULE_UNATTESTED'
mi,f=build(sch={'is_complete_day_snapshot':True,'expected_game_ids':['OTHER']});assert f.reason=='GAME_NOT_IN_SCHEDULE'
m=dict(MAP);m['hr_rate']='hr_rate:OTHER:home:3';s=base()+[mk(m['hr_rate'],.04)];mi,f=build(s=s,m=m);assert f.reason=='CROSS_GAME_FACT_KEY'
for market, fmap in [('hits',{'b_rate':f'b_rate:{G}','p_rate':f'p_rate:{G}','pa_pool':f'pa_pool:{G}'}),('total_bases',{'rates_s':f'rates_s:{G}','rates_d':f'rates_d:{G}','rates_t':f'rates_t:{G}','rates_hr':f'rates_hr:{G}','p_h':f'p_h:{G}','p_hr':f'p_hr:{G}','park':f'park:{G}','pa_pool':f'pa_pool:{G}'}),('pitcher_walks',{'own_bb':f'own_bb:{G}','own_bfp':f'own_bfp:{G}','rolling_league_rate':f'rolling_league_rate:{G}','pool':f'pool:{G}'})]:
 mi,f=build_model_input(market,E,G,fmap,[],NOW,CUT,{k:3600 for k in fmap},runtime_capabilities={},schedule_attestation=SCH,known_entity_ids=IDS); assert f.reason=='MISSING_RUNTIME_CAPABILITY'
s=base();mi1,_=build(s=s);s2=s+[mk(MAP['hr_rate'],.987,et=(CUT+timedelta(minutes=1)).isoformat(),rt=(CUT+timedelta(minutes=2)).isoformat(),sid='late')];mi2,_=build(s=s2);assert mi1.build_hash==mi2.build_hash
s3=base()+[SourceFact('better',MAP['hr_rate'],.04,'OFFICIAL',(NOW-timedelta(hours=1)).isoformat(),(NOW-timedelta(minutes=30)).isoformat(),'CONFIRMED','MODEL_INPUT',1)]
mi3,_=build(s=s3);mi4,_=build(s=list(reversed(s3)));assert mi3.build_hash==mi4.build_hash
print('ALL LIVE FEATURE BRIDGE V0.2 HARDENING TESTS PASS')
