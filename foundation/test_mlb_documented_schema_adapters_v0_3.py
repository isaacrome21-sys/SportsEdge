#!/usr/bin/env python3
from mlb_documented_schema_adapters_v0_3 import *

FETCH='2026-08-10T16:40:00Z'
RAW={
 'gamePk':745444,
 'gameData':{
   'probablePitchers':{'home':{'id':660271},'away':{'id':543039}},
   'status':{'abstractGameState':'Preview','detailedState':'Scheduled'},
   'venue':{'fieldInfo':{'roofType':'Retractable'}},
 },
 'liveData':{'boxscore':{'teams':{'home':{'battingOrder':[1,2,3,4,5,6,7,8,9]},'away':{'battingOrder':[11,12,13,14,15,16,17,18,19]}}}}
}

def raises(fn):
 try: fn(); return False
 except AdapterError: return True

x=adapt_schedule_identity(RAW,'MLB_STATS_API','MLB_OFFICIAL',FETCH)
assert x.game_id=='745444' and x.value==745444
p=adapt_documented_probable_pitcher(RAW,'home','MLB_STATS_API','MLB_OFFICIAL',FETCH)
assert p.value=='660271' and p.status=='PROJECTED' and p.fact_key=='starter:745444:home'
assert raises(lambda: adapt_native_starter_role())
assert raises(lambda: adapt_native_bullpen_availability())
assert raises(lambda: adapt_documented_batting_order(RAW,'home','MLB_STATS_API','MLB_OFFICIAL',FETCH,snapshot_time='2026-08-10T16:35:00Z',pregame_attested=False))
lu=adapt_documented_batting_order(RAW,'home','MLB_STATS_API','MLB_OFFICIAL',FETCH,snapshot_time='2026-08-10T16:35:00Z',pregame_attested=True)
assert len(lu)==9 and lu[0].fact_key=='lineup_slot:745444:home:1' and lu[-1].value=='9'
s=adapt_documented_game_status(RAW,'MLB_STATS_API','MLB_OFFICIAL',FETCH); assert s.value=='Preview'
r=adapt_documented_roof_type(RAW,'MLB_STATS_API','MLB_OFFICIAL',FETCH); assert r.value=='Retractable'
BAD=dict(RAW); BAD['gamePk']='745444'; assert raises(lambda: adapt_schedule_identity(BAD,'MLB_STATS_API','MLB_OFFICIAL',FETCH))
print('ALL DOCUMENTED MLB SCHEMA ADAPTER V0.3 TESTS PASS')
