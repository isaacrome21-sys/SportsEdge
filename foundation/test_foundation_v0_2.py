#!/usr/bin/env python3
import sys, json
from pathlib import Path
from datetime import datetime, timezone, timedelta
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sportsedge_foundation_v0_2 import *
BASE=Path(__file__).resolve().parent
FAIL=[]
def ck(name, cond, detail=''):
    print(('  PASS: ' if cond else '  FAIL: ')+name+(f' {detail}' if detail and not cond else ''))
    if not cond: FAIL.append(name)
now=datetime.now(timezone.utc)
fresh=now.isoformat(); old=(now-timedelta(hours=8)).isoformat(); five=(now-timedelta(days=5)).isoformat(); ancient=(now-timedelta(days=20)).isoformat(); future=(now+timedelta(minutes=1)).isoformat()
print('=== v0.2 source policy adversarial tests ===')
# canonical regression
ck('Athletics doubled name resolves', canonical_team_id('Athletics Athletics')=='ATH')
# duplicate IDs fail closed
try:
    build_source_manifest([{'source_id':'x','fact_key':'injury:p','value':1,'provider':'MLB_OFFICIAL','as_of':fresh,'retrieved_at':fresh},{'source_id':'x','fact_key':'injury:p','value':2,'provider':'MLB_OFFICIAL','as_of':fresh,'retrieved_at':fresh}]); dup=False
except ValueError: dup=True
ck('duplicate source_id rejected', dup)
# fresh authoritative beats stale disagreement for blocking fact
m=build_source_manifest([
 {'source_id':'mlb','fact_key':'starter:G1:home','value':'A','provider':'MLB_OFFICIAL','as_of':fresh,'retrieved_at':fresh},
 {'source_id':'beat','fact_key':'starter:G1:home','value':'B','provider':'BEAT_REPORTER','as_of':old,'retrieved_at':old},])
ck('stale starter disagreement does not create conflict', detect_source_conflicts(m,now)==[], detect_source_conflicts(m,now))
# fresh blocking disagreement blocks regardless authority
m2=build_source_manifest([
 {'source_id':'mlb','fact_key':'starter:G1:home','value':'A','provider':'MLB_OFFICIAL','as_of':fresh,'retrieved_at':fresh},
 {'source_id':'beat','fact_key':'starter:G1:home','value':'B','provider':'BEAT_REPORTER','as_of':fresh,'retrieved_at':fresh},])
ck('fresh starter disagreement blocks', len(detect_source_conflicts(m2,now))==1)
# unverified social cannot satisfy required fact
m3=build_source_manifest([{'source_id':'x','fact_key':'injury:P1','value':'out','provider':'SOCIAL_UNVERIFIED','confidence':'unverified','as_of':fresh,'retrieved_at':fresh}])
r=adjudicate_fact(list(m3.values()),now)
ck('unverified social rejected', r['status']=='NO_USABLE_SOURCE' and r['rejected'][0]['reason']=='UNVERIFIED_SOURCE', r)
# pitch-count uses retrieval freshness but retains event age
m4=build_source_manifest([{'source_id':'pc','fact_key':'pitch_count:P1','value':93,'provider':'MLB_OFFICIAL','as_of':five,'retrieved_at':fresh}])
r=adjudicate_fact(list(m4.values()),now)
ck('5-day-old pitch count freshly retrieved usable', r['status']=='RESOLVED', r)
# old retrieval stale
m5=build_source_manifest([{'source_id':'pc','fact_key':'pitch_count:P1','value':93,'provider':'MLB_OFFICIAL','as_of':five,'retrieved_at':old}])
r=adjudicate_fact(list(m5.values()),now)
ck('8-hour-old pitch-count retrieval stale', r['status']=='NO_USABLE_SOURCE' and r['rejected'][0]['reason']=='STALE_RETRIEVAL', r)
# ancient event cannot be revived
m6=build_source_manifest([{'source_id':'pc','fact_key':'pitch_count:P1','value':93,'provider':'MLB_OFFICIAL','as_of':ancient,'retrieved_at':fresh}])
r=adjudicate_fact(list(m6.values()),now)
ck('20-day-old pitch count cannot be revived', r['status']=='NO_USABLE_SOURCE' and r['rejected'][0]['reason']=='EVENT_TOO_OLD_OR_INVALID', r)
# future timestamps fail closed
m7=build_source_manifest([{'source_id':'inj','fact_key':'injury:P1','value':'out','provider':'MLB_OFFICIAL','as_of':fresh,'retrieved_at':future}])
r=adjudicate_fact(list(m7.values()),now)
ck('future retrieval timestamp fails closed', r['status']=='NO_USABLE_SOURCE', r)
# nonblocking conflict resolved only by unique authority
m8=build_source_manifest([
 {'source_id':'mlb','fact_key':'injury:P1','value':'out','provider':'MLB_OFFICIAL','as_of':fresh,'retrieved_at':fresh},
 {'source_id':'beat','fact_key':'injury:P1','value':'day-to-day','provider':'BEAT_REPORTER','as_of':fresh,'retrieved_at':fresh},])
r=adjudicate_fact(list(m8.values()),now)
ck('nonblocking injury conflict resolves by unique authority', r['status']=='RESOLVED_BY_AUTHORITY' and r['source_id']=='mlb', r)
# required fact conflict blocks even absent dependencies
reg=json.loads((BASE/'test_registry.json').read_text())
status,detail,q=bet_status('moneyline',reg,BASE,m2,now,['starter:G1:home'],{},[])
ck('required blocking fact conflict blocks without dependency list', status=='BLOCKED' and detail['reason']=='SOURCE_CONFLICT', (status,detail))
# model vs bet separation survives stale source
m9=build_source_manifest([{'source_id':'dk','fact_key':'dk_price:G1:ml','value':-120,'provider':'ODDS_API','as_of':fresh,'retrieved_at':old}])
status,detail,q=bet_status('moneyline',reg,BASE,m9,now,['dk_price:G1:ml'],{'dk_price:G1:ml':300},['dk'])
ck('stale price changes BET_STATUS not MODEL_STATUS', status=='STALE' and model_status(reg,'moneyline')['model_eligible'] is True, (status,detail))
print('='*50)
if FAIL:
    print('FAILED',len(FAIL),FAIL); sys.exit(1)
print('ALL FOUNDATION V0.2 TESTS PASS'); sys.exit(0)
