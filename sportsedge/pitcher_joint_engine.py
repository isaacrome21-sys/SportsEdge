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
_OPP_K_CAP=20
_OPP_OUTS_CAP=27
def _price_opp_outs(features:Mapping[str,Any],line:float,side:str,market:str)->tuple[float,float,dict[str,Any],dict[str,Any]]:
    """Validated opponent on-base index -> outs (#1523): rescale own outs by (rel*/rel_i)**beta, split floor/ceil, n = k."""
    adj=features.get("opp_outs_adjustment")
    if not isinstance(adj,Mapping):raise PitcherJointEngineError("opp_outs_adjustment must be object")
    if market!="PITCHER_OUTS" or adj.get("market")!="PITCHER_OUTS":raise PitcherJointEngineError(f"OPP_OUTS_ADJ_NOT_VALIDATED_FOR_{market}")
    if features.get("history_weights") is not None:raise PitcherJointEngineError("opp_outs_adjustment does not accept history_weights")
    pool=_normalize_pool(features.get("history_pool"),"history_pool")
    if not 5<=len(pool)<=10:raise PitcherJointEngineError("opp_outs_adjustment requires 5..10 own starts")
    beta=_f(adj.get("beta"),"opp_outs_adjustment.beta",lo=-1.0);target=_f(adj.get("target_rel"),"opp_outs_adjustment.target_rel")
    rels=adj.get("history_rel")
    if not isinstance(rels,Sequence) or isinstance(rels,(str,bytes)) or len(rels)!=len(pool):raise PitcherJointEngineError("opp_outs_adjustment.history_rel must align with history_pool")
    rels=[_f(r,f"opp_outs_adjustment.history_rel[{i}]") for i,r in enumerate(rels)]
    if target<=0 or any(r<=0 for r in rels):raise PitcherJointEngineError("opp_outs_adjustment indices must be positive")
    k=len(pool);raw=[r["outs"] for r in pool];xs=[min(max(v*(target/h)**beta,0.0),float(_OPP_OUTS_CAP)) for v,h in zip(raw,rels)]
    over=0.0
    for x in xs:
        lo=int(x//1);frac=x-lo
        if lo>=_OPP_OUTS_CAP:over+=1.0 if _OPP_OUTS_CAP>line else 0.0;continue
        over+=(1.0-frac)*(1.0 if lo>line else 0.0)+frac*(1.0 if lo+1>line else 0.0)
    over/=k;under=1.0-over
    post=_posterior(over,under,0.0,float(k),line,market)
    factor=(sum(xs)/sum(raw)) if sum(raw)>0 else 1.0
    info={"beta":beta,"target_rel":target,"history_rel_mean":sum(rels)/k,"factor":factor,"own_starts":k,"opponent_team_id":adj.get("opponent_team_id"),"validated_in":adj.get("validated_in"),"index":adj.get("index")}
    meta={"raw_empirical_p":over if side=="OVER" else under,"raw_push_p":0.0,"effective_history_starts":float(k),"posterior_prior":post["prior"],"opp_outs_adjustment":info}
    identity={"history_pool":pool,"opp_outs_adjustment":{"beta":beta,"target_rel":target,"history_rel":rels,"index":adj.get("index")}}
    return (post["p_over"] if side=="OVER" else post["p_under"]),post["p_push"],meta,identity
def _price_opp_k(features:Mapping[str,Any],line:float,side:str,market:str)->tuple[float,float,dict[str,Any],dict[str,Any]]:
    """Validated opponent-K context lane (#1509): rescale own K by (rel*/rel_i)**beta, split floor/ceil, n = k."""
    adj=features.get("opp_k_adjustment")
    if not isinstance(adj,Mapping):raise PitcherJointEngineError("opp_k_adjustment must be object")
    if market!="PITCHER_K" or adj.get("market")!="PITCHER_K":raise PitcherJointEngineError(f"OPP_K_ADJ_NOT_VALIDATED_FOR_{market}")
    if features.get("history_weights") is not None:raise PitcherJointEngineError("opp_k_adjustment does not accept history_weights")
    pool=_normalize_pool(features.get("history_pool"),"history_pool")
    if len(pool)>10:raise PitcherJointEngineError("opp_k_adjustment requires the last <=10 own starts")
    beta=_f(adj.get("beta"),"opp_k_adjustment.beta");target=_f(adj.get("target_rel"),"opp_k_adjustment.target_rel")
    rels=adj.get("history_rel")
    if not isinstance(rels,Sequence) or isinstance(rels,(str,bytes)) or len(rels)!=len(pool):raise PitcherJointEngineError("opp_k_adjustment.history_rel must align with history_pool")
    rels=[_f(r,f"opp_k_adjustment.history_rel[{i}]") for i,r in enumerate(rels)]
    if target<=0 or any(r<=0 for r in rels):raise PitcherJointEngineError("opp_k_adjustment indices must be positive")
    k=len(pool);raw=[r["strikeouts"] for r in pool];xs=[min(max(v*(target/h)**beta,0.0),float(_OPP_K_CAP)) for v,h in zip(raw,rels)]
    over=0.0
    for x in xs:
        lo=int(x//1);frac=x-lo
        if lo>=_OPP_K_CAP:over+=1.0 if _OPP_K_CAP>line else 0.0;continue
        over+=(1.0-frac)*(1.0 if lo>line else 0.0)+frac*(1.0 if lo+1>line else 0.0)
    over/=k;under=1.0-over
    post=_posterior(over,under,0.0,float(k),line,market)
    factor=(sum(xs)/sum(raw)) if sum(raw)>0 else 1.0
    info={"beta":beta,"target_rel":target,"history_rel_mean":sum(rels)/k,"factor":factor,"own_starts":k,"opponent_team_id":adj.get("opponent_team_id"),"validated_in":adj.get("validated_in")}
    meta={"raw_empirical_p":over if side=="OVER" else under,"raw_push_p":0.0,"effective_history_starts":float(k),"posterior_prior":post["prior"],"opp_k_adjustment":info}
    identity={"history_pool":pool,"opp_k_adjustment":{"beta":beta,"target_rel":target,"history_rel":rels}}
    return (post["p_over"] if side=="OVER" else post["p_under"]),post["p_push"],meta,identity
_UMP_BB_CAP=10
def _price_ump_bb(features:Mapping[str,Any],line:float,side:str,market:str)->tuple[float,float,dict[str,Any],dict[str,Any]]:
    """Validated umpire walk index -> BB (#1528): rescale own BB by (rel*/rel_i)**beta, split floor/ceil, n = k."""
    adj=features.get("ump_bb_adjustment")
    if not isinstance(adj,Mapping):raise PitcherJointEngineError("ump_bb_adjustment must be object")
    if market!="PITCHER_BB" or adj.get("market")!="PITCHER_BB":raise PitcherJointEngineError(f"UMP_BB_ADJ_NOT_VALIDATED_FOR_{market}")
    if features.get("history_weights") is not None:raise PitcherJointEngineError("ump_bb_adjustment does not accept history_weights")
    pool=_normalize_pool(features.get("history_pool"),"history_pool")
    if not 5<=len(pool)<=10:raise PitcherJointEngineError("ump_bb_adjustment requires 5..10 own starts")
    beta=_f(adj.get("beta"),"ump_bb_adjustment.beta");target=_f(adj.get("target_rel"),"ump_bb_adjustment.target_rel")
    rels=adj.get("history_rel")
    if not isinstance(rels,Sequence) or isinstance(rels,(str,bytes)) or len(rels)!=len(pool):raise PitcherJointEngineError("ump_bb_adjustment.history_rel must align with history_pool")
    rels=[_f(r,f"ump_bb_adjustment.history_rel[{i}]") for i,r in enumerate(rels)]
    if target<=0 or any(r<=0 for r in rels):raise PitcherJointEngineError("ump_bb_adjustment indices must be positive")
    k=len(pool);raw=[r["walks_allowed"] for r in pool];xs=[min(max(v*(target/h)**beta,0.0),float(_UMP_BB_CAP)) for v,h in zip(raw,rels)]
    over=0.0
    for x in xs:
        lo=int(x//1);frac=x-lo
        if lo>=_UMP_BB_CAP:over+=1.0 if _UMP_BB_CAP>line else 0.0;continue
        over+=(1.0-frac)*(1.0 if lo>line else 0.0)+frac*(1.0 if lo+1>line else 0.0)
    over/=k;under=1.0-over
    post=_posterior(over,under,0.0,float(k),line,market)
    factor=(sum(xs)/sum(raw)) if sum(raw)>0 else 1.0
    info={"beta":beta,"W":adj.get("W"),"target_rel":target,"history_rel_mean":sum(rels)/k,"factor":factor,"own_starts":k,"umpire_id":adj.get("umpire_id"),"validated_in":adj.get("validated_in")}
    meta={"raw_empirical_p":over if side=="OVER" else under,"raw_push_p":0.0,"effective_history_starts":float(k),"posterior_prior":post["prior"],"ump_bb_adjustment":info}
    identity={"history_pool":pool,"ump_bb_adjustment":{"beta":beta,"W":adj.get("W"),"target_rel":target,"history_rel":rels}}
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
    elif features.get("opp_outs_adjustment") is not None and market=="PITCHER_OUTS" and not float(line).is_integer():
        p,p_push,meta,identity_features=_price_opp_outs(features,line,side,market);meta["weighted"]=False
    elif features.get("ump_bb_adjustment") is not None and market=="PITCHER_BB" and not float(line).is_integer():
        p,p_push,meta,identity_features=_price_ump_bb(features,line,side,market);meta["weighted"]=False
    elif features.get("opp_k_adjustment") is not None and market=="PITCHER_K" and not float(line).is_integer():
        p,p_push,meta,identity_features=_price_opp_k(features,line,side,market);meta["weighted"]=False
    elif features.get("prior_fallback") is not None:
        p,p_push,meta,identity_features=_price_prior_fallback(features,line,side,market);meta["weighted"]=True
    else:
        pool=_normalize_pool(features.get("history_pool"),"history_pool");weights=_weights(features.get("history_weights"),len(pool),"history_weights");p,p_push,meta=_price_values([_value(r,market) for r in pool],weights,line,side,market);meta["weighted"]=features.get("history_weights") is not None;identity_features={"history_pool":pool,"history_weights":weights}
    digest=_sha({"engine":ENGINE_VERSION,"game_id":model_input.get("game_id"),"entity_id":model_input.get("entity_id"),"feature_source_hash":model_input.get("feature_source_hash"),"features":identity_features})
    return {"game_id":model_input.get("game_id"),"market":market,"entity_id":model_input.get("entity_id"),"line":line,"side":side,"model_p":float(p),"push_p":float(p_push),"model_input_hash":digest,"engine_version":ENGINE_VERSION,"seed_policy":"analytic_empirical_bayes_joint_start_rows","mc_paths":0,"meta":meta}
