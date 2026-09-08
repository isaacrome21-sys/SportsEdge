from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Any, Iterable, Mapping
from .truth_gate import american_to_decimal
class DevigError(ValueError):pass
@dataclass(frozen=True)
class DevigResult:
    method:str;candidate_raw_implied:float;opposite_raw_implied:float;overround:float;candidate_fair_probability:float;opposite_fair_probability:float
def _raw_implied(odds):return 1.0/american_to_decimal(odds)
def _strict_bool(value,*,field):
    if type(value) is not bool:raise DevigError(f"{field} must be bool")
    return value
def _required_text(q,key):
    v=q.get(key)
    if v is None or not str(v).strip():raise DevigError(f"paired quote identity missing {key}")
    return str(v).strip()
def _event_instance(q):
    event=q.get("event_id");gn=q.get("game_number")
    if (event is None or not str(event).strip()) and gn is None:raise DevigError("paired quote event instance missing")
    return (str(event).strip() if event not in (None,"") else None,str(gn) if gn is not None else None)
def _identity(q):
    alt=_strict_bool(q.get("is_alternate"),field="is_alternate")
    retrieved=q.get("retrieved_at")
    if not isinstance(retrieved,datetime) or retrieved.tzinfo is None or retrieved.utcoffset() is None:raise DevigError("paired quote retrieved_at missing/invalid")
    market=_required_text(q,"market")
    team=str(q.get("team_id") or "")
    return (_required_text(q,"game_id"),_event_instance(q),_required_text(q,"period"),market,_required_text(q,"entity_id"),team,_required_text(q,"book_key"),alt)
def _line_key(q):
    try:line=float(q["line"])
    except Exception as exc:raise DevigError("paired quote line invalid") from exc
    if not isfinite(line):raise DevigError("paired quote line must be finite")
    return abs(line) if str(q.get("market","")) in {"RUN_LINE","F5_RUN_LINE"} else line
def _complementary_sides(a,b):
    pair={a.upper(),b.upper()};return pair in ({"OVER","UNDER"},{"HOME","AWAY"},{"HOME_ML","AWAY_ML"},{"HOME_RL","AWAY_RL"},{"YES","NO"})
def validate_pair(candidate,opposite):
    # Each quote must be independently structurally valid before pairing.
    from .mlb_market_binding import validate_quote_binding_identity
    try:validate_quote_binding_identity(candidate);validate_quote_binding_identity(opposite)
    except Exception as exc:raise DevigError(f"paired quote binding invalid: {exc}") from exc
    if _identity(candidate)!=_identity(opposite):raise DevigError("paired quote identity mismatch")
    if _line_key(candidate)!=_line_key(opposite):raise DevigError("paired quote line mismatch")
    if not _complementary_sides(str(candidate.get("side","")),str(opposite.get("side",""))):raise DevigError("paired quote sides are not complementary")
def find_paired_quote(candidate,quotes):
    matches=[]
    for quote in quotes:
        if quote is candidate or dict(quote)==dict(candidate):continue
        try:validate_pair(candidate,quote)
        except DevigError:continue
        matches.append(quote)
    if len(matches)!=1:raise DevigError(f"PAIRED_PRICE_REQUIRED_FOR_DEVIG: found={len(matches)}")
    return matches[0]
def multiplicative_devig(candidate,opposite):
    validate_pair(candidate,opposite);q1=_raw_implied(candidate.get("american_odds"));q2=_raw_implied(opposite.get("american_odds"));total=q1+q2
    if not isfinite(total) or total<=0:raise DevigError("invalid paired implied-probability sum")
    p1=q1/total;p2=q2/total
    return DevigResult("MULTIPLICATIVE_V1",q1,q2,total-1.0,p1,p2)
