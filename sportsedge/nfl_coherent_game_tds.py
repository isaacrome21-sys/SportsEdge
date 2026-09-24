"""Allocate anytime-TD outcomes on the same simulated game paths as props.

Adapts disclosed MySpariEdge Touchdown Picks / Game Picks concepts: scoring
environment plus workload, goal-line and close-target role. Sportsbook inputs stay
outside probability generation. Constants are transparent engineering defaults,
not claimed Spari Edge coefficients.
"""
from __future__ import annotations

import random
from math import isfinite
from typing import Any, Mapping, Sequence

from sportsedge.nfl_td_role_model import NflTdRoleError

FORBIDDEN_MARKET_KEYS=frozenset({"price_american","odds","market_no_vig_p","edge_probability_points","ev_per_dollar","fair_american","sportsbook_probability"})


def _num(row: Mapping[str,Any], key:str, *, low:float=0.0, high:float|None=None)->float:
    try:x=float(row[key])
    except (KeyError,TypeError,ValueError) as exc:raise NflTdRoleError(f"TD_PATH_REQUIRED:{key}") from exc
    if not isfinite(x) or x<low or (high is not None and x>high):raise NflTdRoleError(f"TD_PATH_RANGE:{key}")
    return x


def _role_rate(payload:Mapping[str,Any])->float:
    rush=_num(payload,"rush_share",high=1); target=_num(payload,"target_share",high=1)
    goal=_num(payload,"goal_line_carry_share",high=1); close=_num(payload,"close_target_share",high=1)
    mix=_num(payload,"team_rush_td_mix",high=1)
    rushing=min(1.0,.5*rush+.5*goal); receiving=min(1.0,.5*target+.5*close)
    context=payload.get("context") or {}
    if not isinstance(context,Mapping):raise NflTdRoleError("TD_ROLE_CONTEXT_INVALID")
    avail=float(context.get("availability_multiplier",1)); matchup=float(context.get("matchup_multiplier",1))
    if not all(isfinite(x) and 0<=x<=2 for x in (avail,matchup)):raise NflTdRoleError("TD_ROLE_CONTEXT_RANGE")
    return min(1.0,(mix*rushing+(1-mix)*receiving)*avail*matchup)


def simulate_anytime_td_on_game_paths(payload:Mapping[str,Any], game_states:Sequence[Mapping[str,Any]], *, seed:int=21)->list[int]:
    """Return one 0/1 anytime-TD result per shared game-state path."""
    if FORBIDDEN_MARKET_KEYS.intersection(payload):raise NflTdRoleError("MARKET_INPUT_FORBIDDEN")
    if not game_states:raise NflTdRoleError("GAME_STATES_REQUIRED")
    rate=_role_rate(payload); rng=random.Random(int(seed)); out=[]
    for state in game_states:
        if FORBIDDEN_MARKET_KEYS.intersection(state):raise NflTdRoleError("MARKET_INPUT_FORBIDDEN")
        raw=state.get("team_tds")
        if isinstance(raw,bool):raise NflTdRoleError("TEAM_TDS_INTEGER_REQUIRED")
        try:team_tds=int(raw)
        except (TypeError,ValueError) as exc:raise NflTdRoleError("TEAM_TDS_INTEGER_REQUIRED") from exc
        if team_tds<0 or raw!=team_tds:raise NflTdRoleError("TEAM_TDS_INTEGER_REQUIRED")
        out.append(int(any(rng.random()<rate for _ in range(team_tds))))
    return out


def estimate_anytime_td_from_game_paths(payload:Mapping[str,Any], game_states:Sequence[Mapping[str,Any]], *, seed:int=21)->float:
    outcomes=simulate_anytime_td_on_game_paths(payload,game_states,seed=seed)
    return sum(outcomes)/float(len(outcomes))
