"""Anytime-TD RUN IT board with independent model estimate and locked Score B.

The upstream TD estimate must not contain sportsbook market inputs. Pricing uses
a fresh paired YES/NO quote; Score is attached separately from PIT-safe
qualification snapshots. Board order is EV -> edge -> deterministic identity.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping, Sequence

from sports.common.ev_math import EVError, devig, parse_utc
from sportsedge.nfl_run_it_score_binding import score_b_by_identity
from sportsedge.truth_gate import american_to_decimal

TTL=180
SKEW=30

class NflTdBoardError(ValueError): pass

@dataclass(frozen=True)
class TdBoardPick:
    rank:int; game_id:str; player:str; price_american:int; estimate_p:float
    market_no_vig_p:float; edge_probability_points:float; ev_per_dollar:float
    fair_american:int; score_0_100:int

def _ts(x:Any)->datetime:
    try: return parse_utc(x).astimezone(timezone.utc)
    except (EVError,TypeError,ValueError) as e: raise NflTdBoardError("QUOTE_TIME_INVALID") from e

def _american(p:float)->int:
    if not 0<p<1: raise NflTdBoardError("ESTIMATE_P_INVALID")
    return int(round(-100*p/(1-p))) if p>=.5 else int(round(100*(1-p)/p))

def run_td_board(*, estimates:Sequence[Mapping[str,Any]], quotes:Sequence[Mapping[str,Any]],
                 qualification_snapshots:Sequence[Mapping[str,Any]], as_of:datetime|str)->list[TdBoardPick]:
    now=_ts(as_of)
    scores=score_b_by_identity(qualification_snapshots)
    est={}
    for r in estimates:
        if any(k in r for k in ("price_american","odds","market_no_vig_p","edge_probability_points","ev_per_dollar")):
            raise NflTdBoardError("MARKET_INPUT_FORBIDDEN_IN_TD_ESTIMATE")
        key=(str(r.get("game_id","")).strip(),str(r.get("player","")).strip())
        try:p=float(r["estimate_p"])
        except (KeyError,TypeError,ValueError) as e: raise NflTdBoardError("ESTIMATE_P_REQUIRED") from e
        if not all(key) or not isfinite(p) or not 0<p<1: raise NflTdBoardError("TD_ESTIMATE_INVALID")
        est[key]=p
    groups={}
    for q in quotes:
        game=str(q.get("game_id","")).strip(); player=str(q.get("player","")).strip()
        side=str(q.get("selection","")).upper().strip(); book=str(q.get("book","")).lower().strip()
        if not game or not player or side not in {"YES","NO"} or book!="draftkings": raise NflTdBoardError("TD_QUOTE_IDENTITY_INVALID")
        t=_ts(q.get("retrieved_at")); age=(now-t).total_seconds()
        if age>TTL: raise NflTdBoardError("QUOTE_STALE")
        if age < -SKEW: raise NflTdBoardError("QUOTE_CLOCK_SKEW")
        try:price=int(q["price_american"])
        except (KeyError,TypeError,ValueError) as e: raise NflTdBoardError("TD_PRICE_INVALID") from e
        if -100<price<100: raise NflTdBoardError("TD_PRICE_INVALID")
        groups.setdefault((game,player),{})[side]=(price,t)
    rows=[]
    for key,p in est.items():
        pair=groups.get(key,{})
        if set(pair)!={"YES","NO"}: raise NflTdBoardError("PAIRED_TD_PRICE_REQUIRED")
        if abs((pair["YES"][1]-pair["NO"][1]).total_seconds())>SKEW: raise NflTdBoardError("PAIRED_QUOTE_TIME_SKEW")
        dec=[american_to_decimal(pair["YES"][0]),american_to_decimal(pair["NO"][0])]
        try:no_vig=float(devig(dec,trigger_american=400,max_spread_pp=1.0)[0])
        except EVError as e: raise NflTdBoardError(e.code) from e
        price=pair["YES"][0]; ev=p*(american_to_decimal(price)-1)-(1-p); edge=p-no_vig
        score_key=(key[0],"anytime_td",key[1])
        if score_key not in scores: raise NflTdBoardError("QUALIFICATION_SNAPSHOT_REQUIRED_FOR_TD")
        rows.append(dict(game_id=key[0],player=key[1],price_american=price,estimate_p=p,
                         market_no_vig_p=no_vig,edge_probability_points=edge,ev_per_dollar=ev,
                         fair_american=_american(p),score_0_100=scores[score_key]))
    rows.sort(key=lambda r:(-r["ev_per_dollar"],-r["edge_probability_points"],r["game_id"],r["player"]))
    return [TdBoardPick(rank=i,**r) for i,r in enumerate(rows,1)]
