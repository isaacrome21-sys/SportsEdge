"""Transparent NFL anytime-TD role model.

Adapts disclosed concepts from the user's MySpariEdge Touchdown Picks materials:
workload, goal-line role, close-range targets, availability, matchup, and scoring
environment. No proprietary formula, hidden coefficient, or copied weight.
"""
from __future__ import annotations
from dataclasses import dataclass
from math import exp, isfinite
import random
from typing import Any, Mapping

class NflTdRoleError(ValueError): pass

@dataclass(frozen=True)
class TdRoleEstimate:
    player: str; game_id: str; estimate_p: float; expected_team_tds: float
    rushing_td_share: float; receiving_td_share: float; n_sims: int; seed: int

def _num(row: Mapping[str, Any], key: str, *, low: float=0.0, high: float|None=None) -> float:
    try: x=float(row[key])
    except (KeyError,TypeError,ValueError) as exc: raise NflTdRoleError(f"TD_ROLE_REQUIRED:{key}") from exc
    if not isfinite(x) or x<low or (high is not None and x>high): raise NflTdRoleError(f"TD_ROLE_RANGE:{key}")
    return x

def estimate_anytime_td(payload: Mapping[str, Any], *, n_sims: int=20_000, seed: int=21) -> TdRoleEstimate:
    player=str(payload.get("player","")).strip(); game_id=str(payload.get("game_id","")).strip()
    if not player or not game_id: raise NflTdRoleError("TD_ROLE_IDENTITY_INCOMPLETE")
    if isinstance(n_sims,bool) or int(n_sims)!=n_sims or n_sims<=0: raise NflTdRoleError("TD_ROLE_N_SIMS_INVALID")
    expected=_num(payload,"expected_team_tds",high=10.0); rush=_num(payload,"rush_share",high=1.0); target=_num(payload,"target_share",high=1.0)
    goal=_num(payload,"goal_line_carry_share",high=1.0); close=_num(payload,"close_target_share",high=1.0); rush_mix=_num(payload,"team_rush_td_mix",high=1.0)
    rushing=min(1.0,.5*rush+.5*goal); receiving=min(1.0,.5*target+.5*close)
    context=payload.get("context") or {}
    if not isinstance(context,Mapping): raise NflTdRoleError("TD_ROLE_CONTEXT_INVALID")
    vals={k:float(context.get(k,1.0)) for k in ("availability_multiplier","matchup_multiplier","scoring_environment_multiplier")}
    for k,v in vals.items():
        if not isfinite(v) or not 0<=v<=2: raise NflTdRoleError(f"TD_ROLE_CONTEXT_RANGE:{k}")
    player_rate=(rush_mix*rushing+(1-rush_mix)*receiving)*vals["availability_multiplier"]*vals["matchup_multiplier"]
    lam=expected*vals["scoring_environment_multiplier"]
    rng=random.Random(int(seed)); hits=0
    for _ in range(int(n_sims)):
        limit=exp(-lam); product=1.0; team_tds=-1
        while product>limit: team_tds+=1; product*=rng.random()
        hits+=int(any(rng.random()<player_rate for _ in range(max(0,team_tds))))
    return TdRoleEstimate(player,game_id,hits/float(n_sims),lam,rushing,receiving,int(n_sims),int(seed))
