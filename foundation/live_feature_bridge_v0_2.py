#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Set

SCHEMA_VERSION='0.2'
BANNED_FACT_PATTERNS=('market_prob','novig','implied_prob','dk_prob','sportsbook_prob','consensus_prob','closing_prob')
BANNED_SOURCE_KINDS={'SPORTSBOOK_PROBABILITY','MARKET_PROBABILITY','CONSENSUS_PROBABILITY'}

MARKET_CONTRACTS={
 'rbi': {'features':['hr_rate','ob_rate','xb_rate','team_obp','slot'],'requires_lineup_status':True},
 'runs': {'features':['hr_rate','ob_rate','xb_rate','team_obp','slot'],'requires_lineup_status':True},
 'hits': {'features':['b_rate','p_rate','pa_pool'],'requires_lineup_status':True,'capability':'shared_game_effect_sigma_0_20'},
 'total_bases': {'features':['rates_s','rates_d','rates_t','rates_hr','p_h','p_hr','park','pa_pool'],'requires_lineup_status':True,'capability':'shared_game_effect_sigma_0_20'},
 'pitcher_walks': {'features':['own_bb','own_bfp','rolling_league_rate','pool'],'requires_lineup_status':False,'capability':'rolling_pitcher_walks_recalibration_45d'},
}

@dataclass(frozen=True)
class SourceFact:
 source_id:str; fact_key:str; value:Any; provider:str; event_time:str; retrieved_at:str
 status:Optional[str]=None; source_kind:str='MODEL_INPUT'; authority_rank:int=100

@dataclass(frozen=True)
class FeatureProvenance:
 feature:str; source_id:str; provider:str; event_time:str; retrieved_at:str; status:Optional[str]

@dataclass
class ModelInput:
 market:str; entity_id:str; game_id:str; features:Dict[str,Any]; provenance:List[FeatureProvenance]
 lineup_status:Optional[str]; build_hash:str; schema_version:str=SCHEMA_VERSION

@dataclass
class ResolutionFailure:
 reason:str; detail:Dict[str,Any]=field(default_factory=dict)

class BridgeError(Exception): pass

def _parse_ts(s:str)->datetime:
 try: d=datetime.fromisoformat(s.replace('Z','+00:00'))
 except Exception as e: raise BridgeError(f'invalid timestamp {s!r}: {e}')
 if d.tzinfo is None: raise BridgeError(f'timestamp missing timezone: {s!r}')
 return d.astimezone(timezone.utc)

def _json(v): return json.dumps(v,sort_keys=True,separators=(',',':'),default=str)

def _validate_feature(name,v):
 def prob(x): return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(float(x)) and 0<=float(x)<=1
 if name in {'hr_rate','ob_rate','xb_rate','team_obp','b_rate','p_rate','rates_s','rates_d','rates_t','rates_hr','p_h','p_hr','rolling_league_rate'}:
  return prob(v)
 if name=='slot': return isinstance(v,int) and not isinstance(v,bool) and 1<=v<=9
 if name=='park': return isinstance(v,(int,float)) and math.isfinite(float(v)) and 0.25<=float(v)<=4.0
 if name in {'own_bb'}: return isinstance(v,int) and not isinstance(v,bool) and v>=0
 if name in {'own_bfp'}: return isinstance(v,int) and not isinstance(v,bool) and v>0
 if name in {'pa_pool','pool'}: return isinstance(v,(list,tuple)) and len(v)>0 and all(isinstance(x,int) and not isinstance(x,bool) and x>=0 for x in v)
 return False

def resolve_fact(fact_key,sources,now,wager_cutoff,max_age_seconds):
 for pat in BANNED_FACT_PATTERNS:
  if pat in fact_key.lower(): raise BridgeError(f'banned fact_key pattern: {pat}')
 matching=[s for s in sources if s.fact_key==fact_key]
 if not matching: return None,ResolutionFailure('MISSING',{'fact_key':fact_key})
 valid=[]; rejected=[]
 for s in matching:
  if s.source_kind in BANNED_SOURCE_KINDS: raise BridgeError(f'banned source_kind: {s.source_kind}')
  et=_parse_ts(s.event_time); rt=_parse_ts(s.retrieved_at)
  if et>wager_cutoff: rejected.append((s.source_id,'EVENT_AFTER_CUTOFF')); continue
  if rt>wager_cutoff: rejected.append((s.source_id,'RETRIEVED_AFTER_CUTOFF')); continue
  if rt>now: rejected.append((s.source_id,'RETRIEVED_AFTER_NOW')); continue
  if et>rt: rejected.append((s.source_id,'EVENT_AFTER_RETRIEVAL')); continue
  valid.append(s)
 if not valid: return None,ResolutionFailure('TEMPORAL_INVALID',{'fact_key':fact_key,'rejected':rejected})
 values={_json(s.value) for s in valid}
 if len(values)>1: return None,ResolutionFailure('CONFLICT',{'fact_key':fact_key,'conflicting':[{'source_id':s.source_id,'provider':s.provider,'value':s.value} for s in valid]})
 valid.sort(key=lambda s:(s.authority_rank,-_parse_ts(s.retrieved_at).timestamp(),s.source_id))
 chosen=valid[0]
 if max_age_seconds is None: return None,ResolutionFailure('MISSING_TTL',{'fact_key':fact_key})
 age=(now-_parse_ts(chosen.retrieved_at)).total_seconds()
 if age>max_age_seconds: return None,ResolutionFailure('STALE',{'fact_key':fact_key,'age_seconds':age,'limit_seconds':max_age_seconds,'source_id':chosen.source_id})
 return chosen,None

def _build_hash(market,entity_id,game_id,resolved,lineup_status,now,wager_cutoff):
 payload={'schema_version':SCHEMA_VERSION,'market':market,'entity_id':entity_id,'game_id':game_id,'lineup_status':lineup_status,
 'now':now.astimezone(timezone.utc).isoformat(),'wager_cutoff':wager_cutoff.astimezone(timezone.utc).isoformat(),
 'resolved':{k:{'value':v.value,'source_id':v.source_id,'provider':v.provider,'source_kind':v.source_kind,'authority_rank':v.authority_rank,'event_time':v.event_time,'retrieved_at':v.retrieved_at,'status':v.status} for k,v in sorted(resolved.items())}}
 return hashlib.sha256(_json(payload).encode()).hexdigest()

def build_model_input(market,entity_id,game_id,fact_key_map,sources,now,wager_cutoff,freshness_limits,*,runtime_capabilities,schedule_attestation,known_entity_ids:Set[str]):
 if market not in MARKET_CONTRACTS: return None,ResolutionFailure('UNKNOWN_MARKET',{'market':market})
 if not schedule_attestation or schedule_attestation.get('is_complete_day_snapshot') is not True: return None,ResolutionFailure('SCHEDULE_UNATTESTED',{})
 if game_id not in set(schedule_attestation.get('expected_game_ids',[])): return None,ResolutionFailure('GAME_NOT_IN_SCHEDULE',{'game_id':game_id})
 if entity_id not in known_entity_ids: return None,ResolutionFailure('UNKNOWN_ENTITY',{'entity_id':entity_id})
 contract=MARKET_CONTRACTS[market]; required=contract['features']
 if set(fact_key_map)!=set(required): return None,ResolutionFailure('CONTRACT_MISMATCH',{'required':required,'provided':sorted(fact_key_map)})
 cap=contract.get('capability')
 if cap and runtime_capabilities.get(cap) is not True: return None,ResolutionFailure('MISSING_RUNTIME_CAPABILITY',{'required_capability':cap})
 resolved={}; provenance=[]; lineup_status=None
 for feat in required:
  fact_key=fact_key_map[feat]
  if game_id not in fact_key: return None,ResolutionFailure('CROSS_GAME_FACT_KEY',{'feature':feat,'fact_key':fact_key,'game_id':game_id})
  chosen,fail=resolve_fact(fact_key,sources,now,wager_cutoff,freshness_limits.get(feat))
  if fail:return None,fail
  if not _validate_feature(feat,chosen.value): return None,ResolutionFailure('INVALID_FEATURE_VALUE',{'feature':feat,'value':chosen.value})
  resolved[feat]=chosen
  provenance.append(FeatureProvenance(feat,chosen.source_id,chosen.provider,chosen.event_time,chosen.retrieved_at,chosen.status))
  if chosen.status is not None:
   if chosen.status not in {'CONFIRMED','PROJECTED'}: return None,ResolutionFailure('INVALID_LINEUP_STATUS',{'feature':feat,'status':chosen.status})
   if lineup_status and lineup_status!=chosen.status: return None,ResolutionFailure('CONFLICT',{'reason':'lineup_status disagreement'})
   lineup_status=chosen.status
 if contract.get('requires_lineup_status') and lineup_status is None: return None,ResolutionFailure('MISSING_LINEUP_STATUS',{})
 features={feat:resolved[feat].value for feat in required}
 return ModelInput(market,entity_id,game_id,features,provenance,lineup_status,_build_hash(market,entity_id,game_id,resolved,lineup_status,now,wager_cutoff)),None

def model_input_to_json(mi): return asdict(mi)
