"""Broad NFL player-prop RUN IT board with locked Score B.

Design follows disclosed MySpariEdge/Spari Edge presentation concepts only:
independent projection/simulation probability, fair price, paired market economics,
and a separate qualification/role score. No proprietary formula or hidden weight.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping, Sequence

from sports.common.ev_math import EVError, devig, parse_utc
from sportsedge.nfl_run_it_score_binding import score_b_by_identity
from sportsedge.truth_gate import american_to_decimal

PROP_FAMILIES=frozenset({"receptions","receiving_yards","passing_yards","rushing_yards","rush_attempts","pass_attempts","completions","pass_tds","interceptions","rush_receiving_yards"})
TTL=180
SKEW=30
class NflPropBoardError(ValueError): pass

@dataclass(frozen=True)
class PropPick:
    rank:int; game_id:str; player:str; market:str; selection:str; line:float
    price_american:int; estimate_p:float; push_p:float; fair_american:int
    market_no_vig_p:float; edge_probability_points:float; ev_per_dollar:float
    score_0_100:int

def _ts(x:Any)->datetime:
    try:return parse_utc(x).astimezone(timezone.utc)
    except (EVError,TypeError,ValueError) as e:raise NflPropBoardError("QUOTE_TIME_INVALID") from e

def _fair(p:float)->int:
    if not 0<p<1:raise NflPropBoardError("FAIR_P_INVALID")
    return int(round(-100*p/(1-p))) if p>=.5 else int(round(100*(1-p)/p))

def run_prop_board(*,estimates:Sequence[Mapping[str,Any]],quotes:Sequence[Mapping[str,Any]],qualification_snapshots:Sequence[Mapping[str,Any]],as_of:datetime|str)->list[PropPick]:
    now=_ts(as_of); scores=score_b_by_identity(qualification_snapshots); est={}
    forbidden={"price_american","odds","market_no_vig_p","edge_probability_points","ev_per_dollar"}
    for r in estimates:
        if forbidden.intersection(r):raise NflPropBoardError("MARKET_INPUT_FORBIDDEN_IN_PROP_ESTIMATE")
        game=str(r.get("game_id","")).strip(); player=str(r.get("player","")).strip(); market=str(r.get("market","")).strip(); side=str(r.get("selection","")).upper().strip()
        if not game or not player or market not in PROP_FAMILIES or side not in {"OVER","UNDER"}:raise NflPropBoardError("PROP_ESTIMATE_IDENTITY_INVALID")
        try:line=float(r["line"]); p=float(r["estimate_p"]); push=float(r.get("push_p",0))
        except (KeyError,TypeError,ValueError) as e:raise NflPropBoardError("PROP_ESTIMATE_NUMERIC_INVALID") from e
        if not all(map(isfinite,(line,p,push))) or line<0 or p<=0 or p>=1 or push<0 or p+push>1:raise NflPropBoardError("PROP_ESTIMATE_MASS_INVALID")
        est[(game,player,market,side,line)]=(p,push)
    groups={}
    for q in quotes:
        game=str(q.get("game_id","")).strip();player=str(q.get("player","")).strip();market=str(q.get("market","")).strip();side=str(q.get("selection","")).upper().strip();book=str(q.get("book","")).lower().strip()
        try:line=float(q["line"]);price=int(q["price_american"])
        except (KeyError,TypeError,ValueError) as e:raise NflPropBoardError("PROP_QUOTE_NUMERIC_INVALID") from e
        if not game or not player or market not in PROP_FAMILIES or side not in {"OVER","UNDER"} or book!="draftkings" or -100<price<100:raise NflPropBoardError("PROP_QUOTE_IDENTITY_INVALID")
        t=_ts(q.get("retrieved_at"));age=(now-t).total_seconds()
        if age>TTL:raise NflPropBoardError("QUOTE_STALE")
        if age < -SKEW:raise NflPropBoardError("QUOTE_CLOCK_SKEW")
        groups.setdefault((game,player,market,line),{})[side]=(price,t)
    rows=[]
    for (game,player,market,side,line),(p,push) in est.items():
        pair=groups.get((game,player,market,line),{})
        if set(pair)!={"OVER","UNDER"}:raise NflPropBoardError("PAIRED_PROP_PRICE_REQUIRED")
        if abs((pair["OVER"][1]-pair["UNDER"][1]).total_seconds())>SKEW:raise NflPropBoardError("PAIRED_QUOTE_TIME_SKEW")
        dec=[american_to_decimal(pair["OVER"][0]),american_to_decimal(pair["UNDER"][0])]
        try:nv=devig(dec,trigger_american=400,max_spread_pp=1.0)
        except EVError as e:raise NflPropBoardError(e.code) from e
        idx=0 if side=="OVER" else 1; no_vig=float(nv[idx]); price=pair[side][0]
        loss=max(0.0,1-p-push); decisive=p+loss
        if decisive<=0:raise NflPropBoardError("NON_PUSH_MASS_ZERO")
        fair_p=p/decisive; edge=fair_p-no_vig; ev=p*(american_to_decimal(price)-1)-loss
        sk=(game,market,player)
        if sk not in scores:raise NflPropBoardError("QUALIFICATION_SNAPSHOT_REQUIRED_FOR_PROP")
        rows.append(dict(game_id=game,player=player,market=market,selection=side,line=line,price_american=price,estimate_p=p,push_p=push,fair_american=_fair(fair_p),market_no_vig_p=no_vig,edge_probability_points=edge,ev_per_dollar=ev,score_0_100=scores[sk]))
    rows.sort(key=lambda r:(-r["ev_per_dollar"],-r["edge_probability_points"],r["game_id"],r["market"],r["player"],r["selection"],r["line"]))
    return [PropPick(rank=i,**r) for i,r in enumerate(rows,1)]
