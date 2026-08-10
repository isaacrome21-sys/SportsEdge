#!/usr/bin/env python3
from datetime import datetime, timezone, timedelta
from mlb_source_adapters_v0_2 import *
NOW=datetime(2026,8,10,22,tzinfo=timezone.utc)
def iso(h=0): return (NOW-timedelta(hours=h)).isoformat()
G='NYY_BOS_20260810'
def raises(fn):
    try: fn(); return False
    except AdapterError: return True
assert adapt_probable_starter({'game_id':G,'side':'home','player_id':'p','role':'starter','announced_at':iso(2),'confirmed':True},'MLB','MLB_OFFICIAL',iso(1))[0].authority_rank==100
assert raises(lambda: adapt_lineup_card({'game_id':G,'side':'left','confirmed':True,'posted_at':iso(1),'slots':[{'slot':1,'player_id':'p'}]},'MLB','MLB_OFFICIAL',iso()))
assert raises(lambda: adapt_price({'game_id':G,'market':'ml','selection':'BOS','american_odds':-110,'captured_at':'bad'},'DK','TEAM_OFFICIAL',iso()))
assert raises(lambda: adapt_price({'game_id':G,'market':'ml','selection':'BOS','american_odds':-110,'captured_at':iso()},'DK','BOGUS',iso()))
assert raises(lambda: adapt_lineup_card({'game_id':G,'side':'home','confirmed':True,'posted_at':iso(1),'slots':[{'slot':0,'player_id':'p'}]},'MLB','MLB_OFFICIAL',iso()))
assert raises(lambda: adapt_lineup_card({'game_id':G,'side':'home','confirmed':True,'posted_at':iso(1),'slots':[{'slot':1,'player_id':'p'},{'slot':2,'player_id':'p'}]},'MLB','MLB_OFFICIAL',iso()))
assert raises(lambda: adapt_scratch({'game_id':G,'side':'home','slot':10,'player_id':'p','reported_at':iso()},'TEAM','TEAM_OFFICIAL',iso()))
assert raises(lambda: adapt_bullpen_availability({'game_id':G,'side':'home','as_of':iso(),'relievers':[{'player_id':'rp','available':'false'}]},'TEAM','TEAM_OFFICIAL',iso()))
assert raises(lambda: adapt_price({'game_id':G,'market':'ml','selection':'BOS','american_odds':0,'captured_at':iso()},'DK','TEAM_OFFICIAL',iso()))
assert raises(lambda: adapt_price({'game_id':G,'market':'ml','selection':'BOS','american_odds':-110.5,'captured_at':iso()},'DK','TEAM_OFFICIAL',iso()))
raw={'game_id':G,'side':'home','confirmed':True,'posted_at':iso(1),'slots':[{'slot':1,'player_id':'p1'}]}
assert adapt_lineup_card(raw,'MLB','MLB_OFFICIAL',iso())==adapt_lineup_card(raw,'MLB','MLB_OFFICIAL',iso())
print('ALL MLB SOURCE ADAPTER V0.2 TESTS PASS')
