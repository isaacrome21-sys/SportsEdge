"""Transparent NFL role/workload -> shared prop simulation.

Adapts disclosed MySpariEdge-style concepts (projected role, usage, matchup,
injury/context and shared simulation) without proprietary coefficients. Market
prices are forbidden here: this module produces independent estimate_p rows for
nfl_prop_run_it_score_b.
"""
from __future__ import annotations

from math import exp, isfinite, sqrt
import random
from typing import Any, Mapping, Sequence

PROP_STATS = frozenset({
    "receptions", "receiving_yards", "passing_yards", "rushing_yards",
    "rush_attempts", "pass_attempts", "completions", "pass_tds",
    "interceptions", "rush_receiving_yards",
})
ROLE_KEYS = (
    "pass_attempts", "completion_rate", "pass_yards_per_completion",
    "pass_td_rate", "interception_rate", "rush_attempts",
    "rush_yards_per_attempt", "targets", "catch_rate",
    "receiving_yards_per_reception",
)
RATE_KEYS = frozenset({"completion_rate", "pass_td_rate", "interception_rate", "catch_rate"})
FORBIDDEN_MARKET_KEYS = frozenset({
    "price_american", "odds", "market_no_vig_p", "edge_probability_points",
    "ev_per_dollar", "fair_american", "sportsbook_probability",
})

class NflPropSimulationError(ValueError): pass

def _num(value: Any, name: str) -> float:
    if isinstance(value, bool): raise NflPropSimulationError(f"{name}:NUMERIC_REQUIRED")
    try: x=float(value)
    except (TypeError,ValueError) as e: raise NflPropSimulationError(f"{name}:NUMERIC_REQUIRED") from e
    if not isfinite(x): raise NflPropSimulationError(f"{name}:NONFINITE")
    return x

def stabilized_role(payload: Mapping[str,Any], *, prior_strength: float=8.0) -> dict[str,float]:
    if FORBIDDEN_MARKET_KEYS.intersection(payload): raise NflPropSimulationError("MARKET_INPUT_FORBIDDEN")
    prior=payload.get("role_prior"); trailing=payload.get("trailing") or {}
    if not isinstance(prior,Mapping): raise NflPropSimulationError("ROLE_PRIOR_REQUIRED")
    if not isinstance(trailing,Mapping): raise NflPropSimulationError("TRAILING_OBJECT_REQUIRED")
    n=max(0.0,_num(payload.get("sample_size",0),"sample_size")); s=_num(prior_strength,"prior_strength")
    if s<0 or n+s<=0: raise NflPropSimulationError("ROLE_WEIGHT_INVALID")
    out={}
    for k in ROLE_KEYS:
        if k not in prior: raise NflPropSimulationError(f"ROLE_PRIOR_MISSING:{k}")
        p=_num(prior[k],k); o=p if k not in trailing else _num(trailing[k],k)
        v=(s*p+n*o)/(s+n)
        if v<0 or (k in RATE_KEYS and v>1): raise NflPropSimulationError(f"ROLE_VALUE_INVALID:{k}")
        out[k]=v
    return out

def _ctx(payload: Mapping[str,Any], key:str, default:float=1.0)->float:
    c=payload.get("context") or {}
    if not isinstance(c,Mapping): raise NflPropSimulationError("CONTEXT_OBJECT_REQUIRED")
    v=_num(c.get(key,default),f"context.{key}")
    if v<=0: raise NflPropSimulationError(f"CONTEXT_POSITIVE_REQUIRED:{key}")
    return v

def _poisson(rng:random.Random, mu:float)->int:
    if mu<=0:return 0
    if mu>60:return max(0,int(round(rng.gauss(mu,sqrt(mu)))))
    lim=exp(-mu); p=1.0; k=0
    while p>lim: k+=1; p*=rng.random()
    return k-1

def _binom(rng:random.Random,n:int,p:float)->int:
    return sum(rng.random()<p for _ in range(max(0,n)))

def _yards(rng:random.Random,n:int,mean:float)->int:
    return max(0,int(round(sum(rng.gammavariate(2.0,mean/2.0) for _ in range(max(0,n)))))) if mean>0 else 0

def simulate_player(payload:Mapping[str,Any], *, n_sims:int=20000, seed:int=21)->list[dict[str,int]]:
    if isinstance(n_sims,bool) or int(n_sims)!=n_sims or n_sims<=0: raise NflPropSimulationError("N_SIMS_INVALID")
    role=stabilized_role(payload); rng=random.Random(int(seed)); c=payload.get("context") or {}
    sigma=_num(c.get("shared_workload_sigma",.12),"context.shared_workload_sigma")
    if sigma<0: raise NflPropSimulationError("SHARED_SIGMA_INVALID")
    vol=_ctx(payload,"volume_multiplier"); pm=_ctx(payload,"pass_multiplier"); rm=_ctx(payload,"rush_multiplier"); tm=_ctx(payload,"target_multiplier")
    eff=_ctx(payload,"efficiency_multiplier"); pe=_ctx(payload,"pass_efficiency_multiplier"); re=_ctx(payload,"rush_efficiency_multiplier"); ce=_ctx(payload,"receiving_efficiency_multiplier")
    out=[]
    for _ in range(int(n_sims)):
        latent=1.0 if sigma==0 else rng.lognormvariate(-.5*sigma*sigma,sigma)
        pa=_poisson(rng,role["pass_attempts"]*vol*pm*latent); ra=_poisson(rng,role["rush_attempts"]*vol*rm*latent); tg=_poisson(rng,role["targets"]*vol*tm*latent)
        comp=_binom(rng,pa,role["completion_rate"]); rec=_binom(rng,tg,role["catch_rate"])
        py=_yards(rng,comp,role["pass_yards_per_completion"]*eff*pe); ry=_yards(rng,ra,role["rush_yards_per_attempt"]*eff*re); cy=_yards(rng,rec,role["receiving_yards_per_reception"]*eff*ce)
        out.append({"pass_attempts":pa,"completions":comp,"passing_yards":py,"pass_tds":_binom(rng,pa,role["pass_td_rate"]),"interceptions":_binom(rng,pa,role["interception_rate"]),"rush_attempts":ra,"rushing_yards":ry,"receptions":rec,"receiving_yards":cy,"rush_receiving_yards":ry+cy})
    return out

def estimate_prop(draws:Sequence[Mapping[str,Any]], *, game_id:str, player:str, market:str, line:float, selection:str)->dict[str,Any]:
    if market not in PROP_STATS or selection.upper() not in {"OVER","UNDER"} or not draws: raise NflPropSimulationError("PROP_IDENTITY_INVALID")
    threshold=_num(line,"line"); over=under=push=0
    for d in draws:
        v=_num(d.get(market),market)
        if v>threshold: over+=1
        elif v<threshold: under+=1
        else: push+=1
    n=float(len(draws)); side=selection.upper()
    return {"game_id":str(game_id),"player":str(player),"market":market,"selection":side,"line":threshold,"estimate_p":(over if side=="OVER" else under)/n,"push_p":push/n}
