#!/usr/bin/env python3
from datetime import datetime,timezone,timedelta
from live_feature_bridge_v0_3 import SourceFact,resolve_fact
NOW=datetime(2026,8,10,22,tzinfo=timezone.utc); CUT=datetime(2026,8,10,23,tzinfo=timezone.utc)
fk='hr_rate:G:home:3'
low=SourceFact('low',fk,.04,'SOCIAL',(NOW-timedelta(hours=2)).isoformat(),(NOW-timedelta(hours=1)).isoformat(),'CONFIRMED','MODEL_INPUT',0)
high=SourceFact('high',fk,.04,'MLB',(NOW-timedelta(hours=2)).isoformat(),(NOW-timedelta(hours=1,minutes=30)).isoformat(),'CONFIRMED','MODEL_INPUT',100)
chosen,fail=resolve_fact(fk,[low,high],NOW,CUT,7200)
assert not fail and chosen.source_id=='high', (chosen,fail)
chosen2,fail2=resolve_fact(fk,[high,low],NOW,CUT,7200)
assert not fail2 and chosen2.source_id=='high'
print('LIVE FEATURE BRIDGE V0.3 AUTHORITY ORDER PASS')
