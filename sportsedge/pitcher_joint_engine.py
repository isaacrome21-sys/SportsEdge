"""Joint pitcher prop challenger from strictly-prior start outcomes.

Each historical start is one joint row containing strikeouts, outs, earned runs,
hits allowed, and walks allowed. Individual and combined pitcher markets are
marginals of the same empirical distribution, preserving physical support and
cross-market coherence.
"""
from __future__ import annotations

import hashlib
import json
from math import isfinite
from typing import Any, Mapping, Sequence

ENGINE_VERSION = "mlb_pitcher_joint_empirical_v2"
PITCHER_MARKETS=frozenset({"PITCHER_K","PITCHER_OUTS","PITCHER_ER","PITCHER_HITS_ALLOWED","PITCHER_BB","PITCHER_HITS_WALKS_ER","EITHER_PITCHER_HITS_ALLOWED","EITHER_PITCHER_BB","EITHER_PITCHER_ER"})

class PitcherJointEngineError(ValueError):pass

def _f(v:Any,name:str,lo:float=0.0)->float:
    if isinstance(v,bool):raise PitcherJointEngineError(f"{name} must be numeric")
    try:x=float(v)
    except (TypeError,ValueError) as exc:raise PitcherJointEngineError(f"{name} must be numeric") from exc
    if not isfinite(x) or x<lo:raise PitcherJointEngineError(f"{name} invalid")
    return x

def _sha(v:Any)->str:
    raw=json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode();return hashlib.sha256(raw).hexdigest()

def _normalize_pool(raw:Any,name:str)->list[dict[str,int]]:
    if not isinstance(raw,Sequence) or isinstance(raw,(str,bytes)):raise PitcherJointEngineError(f"{name} must be a sequence")
    rows=[];required=("strikeouts","outs","earned_runs","hits_allowed","walks_allowed")
    for i,item in enumerate(raw):
        if not isinstance(item,Mapping):raise PitcherJointEngineError(f"{name}[{i}] must be object")
        row={}
        for key in required:
            x=_f(item.get(key),f"{name}[{i}].{key}")
            if int(x)!=x:raise PitcherJointEngineError(f"{name}[{i}].{key} must be integer")
            row[key]=int(x)
        if not 0<=row["outs"]<=27:raise PitcherJointEngineError(f"{name}[{i}].outs outside [0,27]")
        rows.append(row)
    if len(rows)<5:raise PitcherJointEngineError(f"{name} requires at least 5 prior starts")
    return rows

def _value(row:Mapping[str,int],market:str)->int:
    if market=="PITCHER_K":return row["strikeouts"]
    if market=="PITCHER_OUTS":return row["outs"]
    if market=="PITCHER_ER":return row["earned_runs"]
    if market=="PITCHER_HITS_ALLOWED":return row["hits_allowed"]
    if market=="PITCHER_BB":return row["walks_allowed"]
    if market=="PITCHER_HITS_WALKS_ER":return row["hits_allowed"]+row["walks_allowed"]+row["earned_runs"]
    raise PitcherJointEngineError(f"unsupported single-pitcher market {market}")

def _price_values(values:Sequence[int],line:float,side:str)->tuple[float,float]:
    n=len(values);p_over=sum(v>line for v in values)/n;p_under=sum(v<line for v in values)/n;p_push=sum(v==line for v in values)/n if float(line).is_integer() else 0.0
    if abs(p_over+p_under+p_push-1.0)>1e-12:raise PitcherJointEngineError("probability mass does not conserve")
    return (p_over if side=="OVER" else p_under),p_push

def price_pitcher_market(model_input:Mapping[str,Any])->dict[str,Any]:
    market=str(model_input.get("market","")).upper()
    if market not in PITCHER_MARKETS:raise PitcherJointEngineError(f"unsupported pitcher market {market}")
    side=str(model_input.get("side","")).upper()
    if side not in {"OVER","UNDER"}:raise PitcherJointEngineError("side must be OVER or UNDER")
    line=_f(model_input.get("line"),"line");features=model_input.get("features")
    if not isinstance(features,Mapping):raise PitcherJointEngineError("features required")
    if market.startswith("EITHER_PITCHER_"):
        pool_a=_normalize_pool(features.get("pitcher_a_history"),"pitcher_a_history");pool_b=_normalize_pool(features.get("pitcher_b_history"),"pitcher_b_history")
        base={"EITHER_PITCHER_HITS_ALLOWED":"PITCHER_HITS_ALLOWED","EITHER_PITCHER_BB":"PITCHER_BB","EITHER_PITCHER_ER":"PITCHER_ER"}[market]
        vals_a=[_value(r,base) for r in pool_a];vals_b=[_value(r,base) for r in pool_b];states=[(a,b) for a in vals_a for b in vals_b]
        if side=="OVER":
            wins=sum((a>line) or (b>line) for a,b in states);pushes=sum(not ((a>line) or (b>line)) and ((a==line) or (b==line)) for a,b in states) if float(line).is_integer() else 0
        else:
            wins=sum((a<line) or (b<line) for a,b in states);pushes=sum(not ((a<line) or (b<line)) and ((a==line) or (b==line)) for a,b in states) if float(line).is_integer() else 0
        p=wins/len(states);p_push=pushes/len(states);identity_features={"pitcher_a_history":pool_a,"pitcher_b_history":pool_b}
    else:
        pool=_normalize_pool(features.get("history_pool"),"history_pool");values=[_value(r,market) for r in pool];p,p_push=_price_values(values,line,side);identity_features={"history_pool":pool}
    digest=_sha({"engine":ENGINE_VERSION,"game_id":model_input.get("game_id"),"entity_id":model_input.get("entity_id"),"feature_source_hash":model_input.get("feature_source_hash"),"features":identity_features})
    return {"game_id":model_input.get("game_id"),"market":market,"entity_id":model_input.get("entity_id"),"line":line,"side":side,"model_p":float(p),"push_p":float(p_push),"model_input_hash":digest,"engine_version":ENGINE_VERSION,"seed_policy":"analytic_empirical_joint_start_rows","mc_paths":0}
