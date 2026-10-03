"""Joint pitcher props from strictly-prior starts with finite-sample shrinkage."""
from __future__ import annotations
import hashlib,json
from math import isfinite
from typing import Any,Mapping,Sequence
from .mlb_empirical_bayes import effective_sample_size,feasible_settlements,posterior_settlement_mass
_UPPER_SUPPORT={"PITCHER_OUTS":27}
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
def _normalize_pool(raw:Any,name:str,minimum:int=5)->list[dict[str,int]]:
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
    if len(rows)<minimum:raise PitcherJointEngineError(f"{name} requires at least {minimum} prior starts")
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
def _posterior(over:float,under:float,push:float,n:float,line:float,market:str)->dict[str,Any]:return posterior_settlement_mass(over_mass=over,under_mass=under,push_mass=push,effective_n=n,has_push=float(line).is_integer(),feasible=feasible_settlements(line,lower=0,upper=_UPPER_SUPPORT.get(market)))
def _price_values(values:Sequence[int],weights:Sequence[float],line:float,side:str,market:str)->tuple[float,float,dict[str,Any]]:
    over=sum(w for v,w in zip(values,weights) if v>line);under=sum(w for v,w in zip(values,weights) if v<line);push=sum(w for v,w in zip(values,weights) if v==line) if float(line).is_integer() else 0.0
    if abs(over+under+push-1.0)>1e-12:raise PitcherJointEngineError("probability mass does not conserve")
    n_eff=effective_sample_size(weights,len(weights));post=_posterior(over,under,push,n_eff,line,market)
    return (post["p_over"] if side=="OVER" else post["p_under"]),post["p_push"],{"raw_empirical_p":over if side=="OVER" else under,"raw_push_p":push,"effective_history_starts":float(n_eff),"posterior_prior":post["prior"]}
_FALLBACK_STAT={"PITCHER_OUTS":"outs","PITCHER_K":"strikeouts"}
def _price_prior_fallback(features:Mapping[str,Any],line:float,side:str,market:str)->tuple[float,float,dict[str,Any],dict[str,Any]]:
    """Validated few-starts fallback (#1495): own k in 1..4 blended with m prior pseudo-starts, n = k + m."""
    fb=features.get("prior_fallback")
    if not isinstance(fb,Mapping):raise PitcherJointEngineError("prior_fallback must be object")
    if market not in _FALLBACK_STAT or fb.get("market")!=market:raise PitcherJointEngineError(f"PRIOR_FALLBACK_NOT_VALIDATED_FOR_{market}")
    if float(line).is_integer():raise PitcherJointEngineError("PRIOR_FALLBACK_HALF_LINES_ONLY")
    if features.get("history_weights") is not None:raise PitcherJointEngineError("prior_fallback does not accept history_weights")
    pool=_normalize_pool(features.get("history_pool"),"history_pool",minimum=1)
    if len(pool)>4:raise PitcherJointEngineError("prior_fallback requires 1..4 own starts")
    m=_f(fb.get("pseudo_starts"),"prior_fallback.pseudo_starts")
    if m<=0:raise PitcherJointEngineError("prior_fallback.pseudo_starts must be positive")
    counts=fb.get("counts")
    if not isinstance(counts,Mapping) or not counts:raise PitcherJointEngineError("prior_fallback.counts required")
    table={}
    for key,val in counts.items():
        v=_f(key,"prior_fallback.counts key");c=_f(val,"prior_fallback.counts value")
        if int(v)!=v or int(c)!=c:raise PitcherJointEngineError("prior_fallback.counts must be integers")
        table[int(v)]=table.get(int(v),0)+int(c)
    total=sum(table.values())
    if total<=0:raise PitcherJointEngineError("prior_fallback.counts empty")
    if market=="PITCHER_OUTS" and any(v>27 for v in table):raise PitcherJointEngineError("prior_fallback outs outside [0,27]")
    own=[_value(r,market) for r in pool];k=len(own)
    prior_over=sum(c for v,c in table.items() if v>line)/total
    own_over=sum(1 for v in own if v>line)
    over=(own_over+m*prior_over)/(k+m);under=1.0-over;n=k+m
    post=_posterior(over,under,0.0,n,line,market)
    meta={"raw_empirical_p":over if side=="OVER" else under,"raw_push_p":0.0,"effective_history_starts":float(n),"posterior_prior":post["prior"],"prior_fallback":{"own_starts":k,"pseudo_starts":m,"pool":fb.get("pool"),"season":fb.get("season"),"artifact_sha256":fb.get("artifact_sha256")}}
    identity={"history_pool":pool,"prior_fallback":{"market":market,"pseudo_starts":m,"counts":{str(v):table[v] for v in sorted(table)},"pool":fb.get("pool"),"season":fb.get("season"),"artifact_sha256":fb.get("artifact_sha256")}}
    return (post["p_over"] if side=="OVER" else post["p_under"]),post["p_push"],meta,identity
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
        raw_other=1.0-raw-raw_push;over,under=(raw,raw_other) if side=="OVER" else (raw_other,raw);eff=min(effective_sample_size(wa,len(wa)),effective_sample_size(wb,len(wb)));post=_posterior(over,under,raw_push,eff,line,base);p=post["p_over"] if side=="OVER" else post["p_under"];p_push=post["p_push"];meta={"raw_empirical_p":raw,"raw_push_p":raw_push,"effective_history_starts":float(eff),"posterior_prior":post["prior"],"weighted":features.get("pitcher_a_weights") is not None or features.get("pitcher_b_weights") is not None};identity_features={"pitcher_a_history":a,"pitcher_b_history":b,"pitcher_a_weights":wa,"pitcher_b_weights":wb}
    elif features.get("prior_fallback") is not None:
        p,p_push,meta,identity_features=_price_prior_fallback(features,line,side,market);meta["weighted"]=True
    else:
        pool=_normalize_pool(features.get("history_pool"),"history_pool");weights=_weights(features.get("history_weights"),len(pool),"history_weights");p,p_push,meta=_price_values([_value(r,market) for r in pool],weights,line,side,market);meta["weighted"]=features.get("history_weights") is not None;identity_features={"history_pool":pool,"history_weights":weights}
    digest=_sha({"engine":ENGINE_VERSION,"game_id":model_input.get("game_id"),"entity_id":model_input.get("entity_id"),"feature_source_hash":model_input.get("feature_source_hash"),"features":identity_features})
    return {"game_id":model_input.get("game_id"),"market":market,"entity_id":model_input.get("entity_id"),"line":line,"side":side,"model_p":float(p),"push_p":float(p_push),"model_input_hash":digest,"engine_version":ENGINE_VERSION,"seed_policy":"analytic_empirical_bayes_joint_start_rows","mc_paths":0,"meta":meta}
