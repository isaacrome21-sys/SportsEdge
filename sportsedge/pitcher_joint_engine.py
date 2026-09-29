"""Joint pitcher props from strictly-prior starts with finite-sample shrinkage."""
from __future__ import annotations
import hashlib,json
from math import isfinite
from typing import Any,Mapping,Sequence
from .mlb_empirical_bayes import effective_sample_size,posterior_settlement_mass
ENGINE_VERSION="mlb_pitcher_joint_empirical_bayes_v3"
PITCHER_MARKETS=frozenset({"PITCHER_K","PITCHER_OUTS","PITCHER_ER","PITCHER_HITS_ALLOWED","PITCHER_BB","PITCHER_HITS_WALKS_ER","EITHER_PITCHER_HITS_ALLOWED","EITHER_PITCHER_BB","EITHER_PITCHER_ER"})
class PitcherJointEngineError(ValueError):pass
def _f(v:Any,name:str,lo:float=0.0)->float:
    if isinstance(v,bool):raise PitcherJointEngineError(f"{name} must be numeric")
    try:x=float(v)
    except (TypeError,ValueError) as exc:raise PitcherJointEngineError(f"{name} must be numeric") from exc
    if not isfinite(x) or x<lo:raise PitcherJointEngineError(f"{name} invalid")
    return x
def _sha(v:Any)->str:return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
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
def _weights(raw:Any,n:int,name:str)->list[float]:
    if raw is None:return [1.0/n]*n
    if not isinstance(raw,Sequence) or isinstance(raw,(str,bytes)) or len(raw)!=n:raise PitcherJointEngineError(f"{name} must align with history")
    vals=[_f(v,f"{name}[{i}]") for i,v in enumerate(raw)]
    if any(v<=0 for v in vals):raise PitcherJointEngineError(f"{name} must be positive")
    total=sum(vals);return [v/total for v in vals]
def _value(row:Mapping[str,int],market:str)->int:
    if market=="PITCHER_K":return row["strikeouts"]
    if market=="PITCHER_OUTS":return row["outs"]
    if market=="PITCHER_ER":return row["earned_runs"]
    if market=="PITCHER_HITS_ALLOWED":return row["hits_allowed"]
    if market=="PITCHER_BB":return row["walks_allowed"]
    if market=="PITCHER_HITS_WALKS_ER":return row["hits_allowed"]+row["walks_allowed"]+row["earned_runs"]
    raise PitcherJointEngineError(f"unsupported single-pitcher market {market}")
def _posterior(over:float,under:float,push:float,n:float,line:float)->dict[str,Any]:return posterior_settlement_mass(over_mass=over,under_mass=under,push_mass=push,effective_n=n,has_push=float(line).is_integer())
def _price_values(values:Sequence[int],weights:Sequence[float],line:float,side:str)->tuple[float,float,dict[str,Any]]:
    over=sum(w for v,w in zip(values,weights) if v>line);under=sum(w for v,w in zip(values,weights) if v<line);push=sum(w for v,w in zip(values,weights) if v==line) if float(line).is_integer() else 0.0
    if abs(over+under+push-1.0)>1e-12:raise PitcherJointEngineError("probability mass does not conserve")
    n_eff=effective_sample_size(weights,len(weights));post=_posterior(over,under,push,n_eff,line)
    return (post["p_over"] if side=="OVER" else post["p_under"]),post["p_push"],{"raw_empirical_p":over if side=="OVER" else under,"raw_push_p":push,"effective_history_starts":float(n_eff),"posterior_prior":post["prior"]}
def price_pitcher_market(model_input:Mapping[str,Any])->dict[str,Any]:
    market=str(model_input.get("market","")).upper()
    if market not in PITCHER_MARKETS:raise PitcherJointEngineError(f"unsupported pitcher market {market}")
    side=str(model_input.get("side","")).upper()
    if side not in {"OVER","UNDER"}:raise PitcherJointEngineError("side must be OVER or UNDER")
    line=_f(model_input.get("line"),"line");features=model_input.get("features")
    if not isinstance(features,Mapping):raise PitcherJointEngineError("features required")
    if market.startswith("EITHER_PITCHER_"):
        a=_normalize_pool(features.get("pitcher_a_history"),"pitcher_a_history");b=_normalize_pool(features.get("pitcher_b_history"),"pitcher_b_history");wa=_weights(features.get("pitcher_a_weights"),len(a),"pitcher_a_weights");wb=_weights(features.get("pitcher_b_weights"),len(b),"pitcher_b_weights")
        base={"EITHER_PITCHER_HITS_ALLOWED":"PITCHER_HITS_ALLOWED","EITHER_PITCHER_BB":"PITCHER_BB","EITHER_PITCHER_ER":"PITCHER_ER"}[market];states=[(_value(x,base),_value(y,base),wx*wy) for x,wx in zip(a,wa) for y,wy in zip(b,wb)]
        if side=="OVER":raw=sum(w for x,y,w in states if (x>line) or (y>line));raw_push=sum(w for x,y,w in states if not((x>line) or (y>line)) and ((x==line) or (y==line))) if float(line).is_integer() else 0.0
        else:raw=sum(w for x,y,w in states if (x<line) or (y<line));raw_push=sum(w for x,y,w in states if not((x<line) or (y<line)) and ((x==line) or (y==line))) if float(line).is_integer() else 0.0
        raw_other=1.0-raw-raw_push;over,under=(raw,raw_other) if side=="OVER" else (raw_other,raw);eff=min(effective_sample_size(wa,len(wa)),effective_sample_size(wb,len(wb)));post=_posterior(over,under,raw_push,eff,line);p=post["p_over"] if side=="OVER" else post["p_under"];p_push=post["p_push"];meta={"raw_empirical_p":raw,"raw_push_p":raw_push,"effective_history_starts":float(eff),"posterior_prior":post["prior"],"weighted":features.get("pitcher_a_weights") is not None or features.get("pitcher_b_weights") is not None};identity_features={"pitcher_a_history":a,"pitcher_b_history":b,"pitcher_a_weights":wa,"pitcher_b_weights":wb}
    else:
        pool=_normalize_pool(features.get("history_pool"),"history_pool");weights=_weights(features.get("history_weights"),len(pool),"history_weights");p,p_push,meta=_price_values([_value(r,market) for r in pool],weights,line,side);meta["weighted"]=features.get("history_weights") is not None;identity_features={"history_pool":pool,"history_weights":weights}
    digest=_sha({"engine":ENGINE_VERSION,"game_id":model_input.get("game_id"),"entity_id":model_input.get("entity_id"),"feature_source_hash":model_input.get("feature_source_hash"),"features":identity_features})
    return {"game_id":model_input.get("game_id"),"market":market,"entity_id":model_input.get("entity_id"),"line":line,"side":side,"model_p":float(p),"push_p":float(p_push),"model_input_hash":digest,"engine_version":ENGINE_VERSION,"seed_policy":"analytic_empirical_bayes_joint_start_rows","mc_paths":0,"meta":meta}
