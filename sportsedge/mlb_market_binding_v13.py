"""Audit-grade MLB wager binding contract and runtime adapters.

The model is not allowed to invent sportsbook/event identity. Runtime quote
binding is performed from normalized sportsbook fields plus the canonical MLB
schedule game object. Full probability binding happens only after the model
returns a probability/readout, and a failure blocks that row rather than the
whole card.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Any, Mapping

TWO_WAY = "TWO_WAY"
N_WAY = "N_WAY"
FULL_GAME = "FULL_GAME"
F5 = "F5"
FIRST_INNING = "FIRST_INNING"
TEAM = "TEAM"
GAME = "GAME"
BATTER = "BATTER"
PITCHER = "PITCHER"
MULTI_PITCHER = "MULTI_PITCHER"
FIELD = "FIELD"
NO_THRESHOLD = "NO_THRESHOLD"
INTEGER_PUSHABLE = "INTEGER_PUSHABLE"
RUN_LINE_SIGNED = "RUN_LINE_SIGNED"
THRESHOLD_DOMAIN_NONE = "NONE"
THRESHOLD_DOMAIN_NON_NEGATIVE = "NON_NEGATIVE"
THRESHOLD_DOMAIN_RUN_LINE = "RUN_LINE"
MULTIPLICATIVE_2WAY = "MULTIPLICATIVE_2WAY"
NWAY_UNAUTHORIZED = "NWAY_UNAUTHORIZED"
SETTLE_GAME_RESULT = "SETTLE_GAME_RESULT"
SETTLE_STAT_LINE = "SETTLE_STAT_LINE"
SETTLE_ORDERING = "SETTLE_ORDERING"
SETTLE_PITCHER_DECISION = "SETTLE_PITCHER_DECISION"
VALID_SETTLEMENTS = frozenset({"WIN", "LOSS", "PUSH", "VOID", "CANCELLED"})
PRODUCTION_WIRED_MARKETS = frozenset({"MONEYLINE", "RUN_LINE", "TOTALS", "TEAM_TOTALS"})

class BindingError(ValueError):
    pass

@dataclass(frozen=True)
class MarketBinding:
    market_id: str; family: str; ways: str; period: str; entity_type: str
    sides: tuple[str, ...]; threshold_semantics: str; threshold_domain: str
    devig_class: str; settlement_class: str; push_supported: bool
    production_wired: bool = False
    def __post_init__(self) -> None:
        if self.ways not in {TWO_WAY, N_WAY}: raise BindingError(f"BAD_WAYS:{self.market_id}")
        if self.threshold_domain not in {THRESHOLD_DOMAIN_NONE, THRESHOLD_DOMAIN_NON_NEGATIVE, THRESHOLD_DOMAIN_RUN_LINE}: raise BindingError(f"BAD_THRESHOLD_DOMAIN:{self.market_id}:{self.threshold_domain}")
        expected = THRESHOLD_DOMAIN_NONE if self.threshold_semantics == NO_THRESHOLD else THRESHOLD_DOMAIN_RUN_LINE if self.threshold_semantics == RUN_LINE_SIGNED else THRESHOLD_DOMAIN_NON_NEGATIVE
        if self.threshold_domain != expected: raise BindingError(f"THRESHOLD_DOMAIN_SEMANTICS_MISMATCH:{self.market_id}:{self.threshold_domain}!={expected}")
        if self.ways == N_WAY and self.devig_class == MULTIPLICATIVE_2WAY: raise BindingError(f"NWAY_THROUGH_TWO_WAY_DEVIG:{self.market_id}")

def _mb(mid, family, period, entity, sides, threshold, domain, settlement, push, *, ways=TWO_WAY, devig=MULTIPLICATIVE_2WAY):
    return MarketBinding(mid, family, ways, period, entity, sides, threshold, domain, devig, settlement, push, mid in PRODUCTION_WIRED_MARKETS)

MARKET_BINDINGS: dict[str, MarketBinding] = {}
def _add(spec):
    if spec.market_id in MARKET_BINDINGS: raise BindingError(f"DUPLICATE_MARKET_ID:{spec.market_id}")
    MARKET_BINDINGS[spec.market_id] = spec

_add(_mb("MONEYLINE","GAME_LINE",FULL_GAME,TEAM,("HOME","AWAY"),NO_THRESHOLD,THRESHOLD_DOMAIN_NONE,SETTLE_GAME_RESULT,False))
_add(_mb("RUN_LINE","GAME_LINE",FULL_GAME,TEAM,("HOME","AWAY"),RUN_LINE_SIGNED,THRESHOLD_DOMAIN_RUN_LINE,SETTLE_GAME_RESULT,False))
_add(_mb("TOTALS","GAME_TOTAL",FULL_GAME,GAME,("OVER","UNDER"),INTEGER_PUSHABLE,THRESHOLD_DOMAIN_NON_NEGATIVE,SETTLE_STAT_LINE,True))
_add(_mb("TEAM_TOTALS","TEAM_TOTAL",FULL_GAME,TEAM,("OVER","UNDER"),INTEGER_PUSHABLE,THRESHOLD_DOMAIN_NON_NEGATIVE,SETTLE_STAT_LINE,True))
_add(_mb("F5_MONEYLINE","GAME_LINE",F5,TEAM,("HOME","AWAY"),NO_THRESHOLD,THRESHOLD_DOMAIN_NONE,SETTLE_GAME_RESULT,True))
_add(_mb("F5_RUN_LINE","GAME_LINE",F5,TEAM,("HOME","AWAY"),RUN_LINE_SIGNED,THRESHOLD_DOMAIN_RUN_LINE,SETTLE_GAME_RESULT,False))
_add(_mb("F5_TOTALS","GAME_TOTAL",F5,GAME,("OVER","UNDER"),INTEGER_PUSHABLE,THRESHOLD_DOMAIN_NON_NEGATIVE,SETTLE_STAT_LINE,True))
_add(_mb("F5_TEAM_TOTALS","TEAM_TOTAL",F5,TEAM,("OVER","UNDER"),INTEGER_PUSHABLE,THRESHOLD_DOMAIN_NON_NEGATIVE,SETTLE_STAT_LINE,True))
_add(_mb("NRFI","FIRST_INNING",FIRST_INNING,GAME,("YES","NO"),NO_THRESHOLD,THRESHOLD_DOMAIN_NONE,SETTLE_STAT_LINE,False))
_add(_mb("YRFI","FIRST_INNING",FIRST_INNING,GAME,("YES","NO"),NO_THRESHOLD,THRESHOLD_DOMAIN_NONE,SETTLE_STAT_LINE,False))
for _m in ("HITS","TOTAL_BASES","HOME_RUNS","RBI","RUNS","SINGLES","DOUBLES","TRIPLES","EXTRA_BASE_HITS","BATTER_BB","BATTER_K","STOLEN_BASES","HITS_RUNS_RBIS","RUNS_RBIS","HITS_STOLEN_BASES","HITS_RUNS_STOLEN_BASES","HITS_WALKS_STOLEN_BASES"):
    _add(_mb(_m,"BATTER_PROP",FULL_GAME,BATTER,("OVER","UNDER"),INTEGER_PUSHABLE,THRESHOLD_DOMAIN_NON_NEGATIVE,SETTLE_STAT_LINE,True))
for _m in ("PITCHER_K","PITCHER_OUTS","PITCHER_HITS_ALLOWED","PITCHER_BB","PITCHER_ER","PITCHER_HITS_WALKS_ER"):
    _add(_mb(_m,"PITCHER_PROP",FULL_GAME,PITCHER,("OVER","UNDER"),INTEGER_PUSHABLE,THRESHOLD_DOMAIN_NON_NEGATIVE,SETTLE_STAT_LINE,True))
for _m in ("EITHER_PITCHER_HITS_ALLOWED","EITHER_PITCHER_BB","EITHER_PITCHER_ER"):
    _add(_mb(_m,"PITCHER_PROP",FULL_GAME,MULTI_PITCHER,("YES","NO"),INTEGER_PUSHABLE,THRESHOLD_DOMAIN_NON_NEGATIVE,SETTLE_STAT_LINE,True))
_add(_mb("FIRST_HOME_RUN","SPECIAL",FULL_GAME,FIELD,("PLAYER","NO_HOME_RUN"),NO_THRESHOLD,THRESHOLD_DOMAIN_NONE,SETTLE_ORDERING,False,ways=N_WAY,devig=NWAY_UNAUTHORIZED))
_add(_mb("PITCHER_RECORD_WIN","SPECIAL",FULL_GAME,PITCHER,("YES","NO"),NO_THRESHOLD,THRESHOLD_DOMAIN_NONE,SETTLE_PITCHER_DECISION,False))
if len(MARKET_BINDINGS) != 38: raise BindingError(f"MLB_BINDING_SPEC_COUNT:{len(MARKET_BINDINGS)}")

_PERIOD_ALIASES={"FG":FULL_GAME,"FULL_GAME":FULL_GAME,"F5":F5,"5":F5,"1ST":FIRST_INNING,"1":FIRST_INNING,"FIRST_INNING":FIRST_INNING}
_SIDE_ALIASES={"HOME_ML":"HOME","AWAY_ML":"AWAY","HOME_RL":"HOME","AWAY_RL":"AWAY"}
_DOMAIN_CEILING={"GAME_TOTAL":100.0,"TEAM_TOTAL":100.0,"BATTER_PROP":100.0,"PITCHER_PROP":100.0}

def _required(row, field, mid):
    if field not in row or row[field] in (None, ""): raise BindingError(f"MISSING_REQUIRED_FIELD:{mid}:{field}")
    return row[field]
def _american(odds, mid):
    if isinstance(odds,bool) or not isinstance(odds,(int,float)): raise BindingError(f"PRICE_NOT_NUMERIC:{mid}:{odds!r}")
    v=float(odds)
    if not isfinite(v) or v!=int(v) or -100<v<100: raise BindingError(f"PRICE_INVALID_AMERICAN:{mid}:{odds!r}")
    return int(v)
def _aware(v, field, mid):
    if not isinstance(v,datetime) or v.tzinfo is None or v.utcoffset() is None: raise BindingError(f"TIMESTAMP_NOT_AWARE:{mid}:{field}")
    return v
def _period(v): return _PERIOD_ALIASES.get(str(v).upper(),str(v).upper())
def _side(v): raw=str(v).upper(); return _SIDE_ALIASES.get(raw,raw)
def _line_for_spec(spec, raw, mid):
    if spec.threshold_semantics==NO_THRESHOLD:
        if raw not in (None,"",0,0.0): raise BindingError(f"UNEXPECTED_THRESHOLD:{mid}:{raw!r}")
        return None
    if isinstance(raw,bool) or not isinstance(raw,(int,float)) or not isfinite(float(raw)): raise BindingError(f"THRESHOLD_NOT_FINITE_NUMERIC:{mid}:{raw!r}")
    line=float(raw)
    if spec.threshold_semantics==RUN_LINE_SIGNED:
        if line not in (-1.5,1.5): raise BindingError(f"ILLEGAL_RUN_LINE:{mid}:{line}")
        return line
    if round(abs(line)%1.0,6) not in (0.0,0.5): raise BindingError(f"ILLEGAL_THRESHOLD_INCREMENT:{mid}:{line}")
    if spec.threshold_domain==THRESHOLD_DOMAIN_NON_NEGATIVE and line<0: raise BindingError(f"THRESHOLD_OUT_OF_DOMAIN:{mid}:{line}")
    ceiling=_DOMAIN_CEILING.get(spec.family)
    if ceiling is not None and line>ceiling: raise BindingError(f"THRESHOLD_ABOVE_DOMAIN_CEILING:{mid}:{line}>{ceiling}")
    return line

def validate_quote_binding(row: Mapping[str,Any]) -> None:
    mid=str(row.get("market_id") or row.get("market") or "").upper(); spec=MARKET_BINDINGS.get(mid)
    if spec is None: raise BindingError(f"UNKNOWN_MARKET_ID:{mid!r}")
    for f in ("event_id","game_number","book_key","retrieved_at","period","side","american_odds","is_alternate"): _required(row,f,mid)
    if type(row["is_alternate"]) is not bool: raise BindingError(f"ALTERNATE_FLAG_NOT_BOOL:{mid}")
    _american(row["american_odds"],mid); _aware(row["retrieved_at"],"retrieved_at",mid)
    gn=row["game_number"]
    if isinstance(gn,bool) or not isinstance(gn,int) or gn not in (1,2): raise BindingError(f"ILLEGAL_GAME_NUMBER:{mid}:{gn!r}")
    if _period(row["period"])!=spec.period: raise BindingError(f"PERIOD_MISMATCH:{mid}:{row['period']}!={spec.period}")
    side=_side(row["side"])
    if side not in spec.sides: raise BindingError(f"ILLEGAL_SIDE:{mid}:{side}:{spec.sides}")
    line=_line_for_spec(spec,row.get("line"),mid)
    if spec.entity_type==TEAM:
        team=str(_required(row,"team_id",mid)); home=str(_required(row,"event_home_team_id",mid)); away=str(_required(row,"event_away_team_id",mid))
        if not home or not away or home==away: raise BindingError(f"EVENT_TEAM_IDENTITY_INVALID:{mid}")
        if team not in {home,away}: raise BindingError(f"TEAM_NOT_IN_EVENT:{mid}:{team}")
        if side=="HOME" and team!=home: raise BindingError(f"SIDE_TEAM_MISMATCH:{mid}:HOME:{team}!={home}")
        if side=="AWAY" and team!=away: raise BindingError(f"SIDE_TEAM_MISMATCH:{mid}:AWAY:{team}!={away}")
    elif spec.entity_type in {BATTER,PITCHER}: _required(row,"entity_id",mid)
    elif spec.entity_type==MULTI_PITCHER:
        ids=row.get("entity_ids")
        if not isinstance(ids,(list,tuple)) or len(ids)!=2 or len(set(map(str,ids)))!=2 or not all(str(x).strip() for x in ids): raise BindingError(f"MULTI_ENTITY_REQUIRES_TWO_DISTINCT_IDS:{mid}:{ids!r}")
    elif spec.entity_type==FIELD:
        outcome=_required(row,"outcome_id",mid)
        if side=="PLAYER" and not str(row.get("outcome_player_id") or "").strip(): raise BindingError(f"NWAY_PLAYER_OUTCOME_REQUIRES_PLAYER_ID:{mid}")
        if side=="NO_HOME_RUN" and outcome!="NO_HOME_RUN": raise BindingError(f"NWAY_NO_HOME_RUN_ID_INVALID:{mid}:{outcome!r}")
    push=row.get("push_probability")
    if push is not None:
        if isinstance(push,bool) or not isinstance(push,(int,float)) or not isfinite(float(push)) or not 0<=float(push)<=1: raise BindingError(f"PUSH_PROBABILITY_OUT_OF_RANGE:{mid}:{push!r}")
        if line is not None and abs(line*2)%2==1 and float(push)>0: raise BindingError(f"HALF_POINT_GIVEN_PUSH_MASS:{mid}:{line}:{push}")
        if float(push)>0 and not spec.push_supported: raise BindingError(f"PUSH_NOT_SUPPORTED:{mid}:{push}")

def validate_binding(row: Mapping[str,Any]) -> None:
    validate_quote_binding(row); mid=str(row.get("market_id") or row.get("market") or "").upper(); spec=MARKET_BINDINGS[mid]
    for f in ("probability_market_id","probability_bound_market_id"):
        if str(_required(row,f,mid)).upper()!=mid: raise BindingError(f"{f.upper()}_MISMATCH:{mid}:{row.get(f)!r}")
    if spec.entity_type==TEAM:
        a=str(_required(row,"team_id",mid)); b=str(_required(row,"probability_team_id",mid))
        if a!=b: raise BindingError(f"PROBABILITY_TEAM_MISMATCH:{mid}:{a}!={b}")
    elif spec.entity_type in {BATTER,PITCHER}:
        a=str(_required(row,"entity_id",mid)); b=str(_required(row,"probability_entity_id",mid))
        if a!=b: raise BindingError(f"PROBABILITY_ENTITY_MISMATCH:{mid}:{a}!={b}")
    elif spec.entity_type==MULTI_PITCHER:
        if tuple(map(str,row.get("entity_ids") or ()))!=tuple(map(str,_required(row,"probability_entity_ids",mid))): raise BindingError(f"MULTI_ENTITY_PROBABILITY_MISMATCH:{mid}")
    line=_line_for_spec(spec,row.get("line"),mid)
    if spec.threshold_semantics!=NO_THRESHOLD:
        pline=_required(row,"probability_line",mid)
        if float(pline)!=float(line): raise BindingError(f"PROBABILITY_THRESHOLD_MISMATCH:{mid}:{line}!={pline}")
    devig=row.get("devig_method")
    if spec.devig_class==NWAY_UNAUTHORIZED and devig: raise BindingError(f"NWAY_DEVIG_UNAUTHORIZED:{mid}:{devig}")
    if devig and spec.devig_class==MULTIPLICATIVE_2WAY and devig!="MULTIPLICATIVE_V1": raise BindingError(f"UNAPPROVED_DEVIG_METHOD:{mid}:{devig}")

def validate_quote_pair(a: Mapping[str,Any], b: Mapping[str,Any], *, max_skew_seconds: float=30.0) -> None:
    validate_quote_binding(a); validate_quote_binding(b)
    ma=str(a.get("market_id") or a.get("market") or "").upper(); mb=str(b.get("market_id") or b.get("market") or "").upper()
    if ma!=mb: raise BindingError(f"PAIRED_QUOTE_MARKET_MISMATCH:{ma}!={mb}")
    for f in ("event_id","game_number","book_key"):
        if a.get(f)!=b.get(f): raise BindingError(f"PAIRED_QUOTE_MISMATCH:{f}")
    if _period(a.get("period"))!=_period(b.get("period")): raise BindingError("PAIRED_QUOTE_MISMATCH:period")
    if a.get("is_alternate")!=b.get("is_alternate"): raise BindingError("PAIRED_QUOTE_MISMATCH:is_alternate")
    sa,sb=_side(a.get("side")),_side(b.get("side")); spec=MARKET_BINDINGS[ma]
    if sa==sb: raise BindingError("PAIRED_QUOTE_SAME_SIDE")
    if spec.ways==N_WAY: raise BindingError(f"PAIRED_QUOTE_UNSUPPORTED:{ma}")
    if ma in {"MONEYLINE","F5_MONEYLINE"}:
        if {sa,sb}!={"HOME","AWAY"}: raise BindingError(f"PAIRED_QUOTE_SIDES_NOT_HOME_AWAY:{ma}")
        if str(a.get("team_id"))==str(b.get("team_id")): raise BindingError(f"PAIRED_QUOTE_SAME_TEAM:{ma}")
    elif ma in {"RUN_LINE","F5_RUN_LINE"}:
        if {sa,sb}!={"HOME","AWAY"}: raise BindingError(f"PAIRED_QUOTE_SIDES_NOT_HOME_AWAY:{ma}")
        if float(a["line"])!=-float(b["line"]): raise BindingError(f"PAIRED_QUOTE_RUN_LINE_NOT_OPPOSITE:{ma}:{a['line']}/{b['line']}")
    elif ma in {"TEAM_TOTALS","F5_TEAM_TOTALS"}:
        if {sa,sb}!={"OVER","UNDER"} or str(a.get("team_id"))!=str(b.get("team_id")) or float(a["line"])!=float(b["line"]): raise BindingError(f"PAIRED_QUOTE_TEAM_TOTAL_MISMATCH:{ma}")
    elif spec.entity_type in {BATTER,PITCHER}:
        if {sa,sb} not in ({"OVER","UNDER"},{"YES","NO"}): raise BindingError(f"PAIRED_QUOTE_SIDES_NOT_COMPLEMENTARY:{ma}")
        if str(a.get("entity_id"))!=str(b.get("entity_id")): raise BindingError(f"PAIRED_QUOTE_PLAYER_MISMATCH:{ma}")
        if spec.threshold_semantics!=NO_THRESHOLD and float(a["line"])!=float(b["line"]): raise BindingError(f"PAIRED_QUOTE_LINE_MISMATCH:{ma}")
    elif spec.entity_type==MULTI_PITCHER:
        if tuple(map(str,a.get("entity_ids") or ()))!=tuple(map(str,b.get("entity_ids") or ())): raise BindingError(f"PAIRED_QUOTE_PITCHER_PAIR_MISMATCH:{ma}")
        if float(a["line"])!=float(b["line"]): raise BindingError(f"PAIRED_QUOTE_LINE_MISMATCH:{ma}")
    else:
        if {sa,sb} not in ({"OVER","UNDER"},{"YES","NO"}): raise BindingError(f"PAIRED_QUOTE_SIDES_NOT_COMPLEMENTARY:{ma}")
        if spec.threshold_semantics!=NO_THRESHOLD and float(a["line"])!=float(b["line"]): raise BindingError(f"PAIRED_QUOTE_LINE_MISMATCH:{ma}")
    skew=abs((_aware(a["retrieved_at"],"retrieved_at",ma)-_aware(b["retrieved_at"],"retrieved_at",ma)).total_seconds())
    if skew>max_skew_seconds: raise BindingError(f"PAIRED_QUOTE_SKEW_EXCEEDED:{skew:.1f}>{max_skew_seconds}")

def attach_runtime_binding_context(quote: Mapping[str,Any], game: Any) -> dict[str,Any]:
    out=dict(quote); out["event_id"]=str(game.game_pk); out["game_number"]=game.game_number; out["event_home_team_id"]=str(game.home_team_id); out["event_away_team_id"]=str(game.away_team_id)
    spec=MARKET_BINDINGS.get(str(out.get("market","")).upper())
    if spec is None: raise BindingError(f"UNKNOWN_MARKET_ID:{out.get('market')!r}")
    if spec.entity_type==TEAM: out["team_id"]=str(out.get("entity_id") or "")
    elif spec.entity_type==MULTI_PITCHER:
        raw=str(out.get("entity_id") or ""); out["entity_ids"]=raw.split("|") if raw else []
    elif spec.entity_type==FIELD:
        out["outcome_id"]=str(out.get("outcome_id") or out.get("entity_id") or "")
        if _side(out.get("side"))=="PLAYER": out["outcome_player_id"]=str(out.get("entity_id") or "")
    return out

def runtime_quote_binding_row(quote: Mapping[str,Any]) -> dict[str,Any]:
    mid=str(quote.get("market") or "").upper(); spec=MARKET_BINDINGS.get(mid)
    if spec is None: raise BindingError(f"UNKNOWN_MARKET_ID:{mid!r}")
    row={"event_id":quote.get("event_id"),"game_number":quote.get("game_number"),"book_key":quote.get("book_key"),"retrieved_at":quote.get("retrieved_at"),"market_id":mid,"period":quote.get("period"),"side":_side(quote.get("side")),"american_odds":quote.get("american_odds"),"is_alternate":quote.get("is_alternate"),"line":None if spec.threshold_semantics==NO_THRESHOLD else quote.get("line")}
    for f in ("team_id","event_home_team_id","event_away_team_id","entity_id","entity_ids","outcome_id","outcome_player_id"):
        if f in quote: row[f]=quote[f]
    return row

def runtime_full_binding_row(quote: Mapping[str,Any], model_output: Mapping[str,Any]) -> dict[str,Any]:
    row=runtime_quote_binding_row(quote); mid=row["market_id"]; spec=MARKET_BINDINGS[mid]; model_market=str(model_output.get("market") or "").upper()
    row["probability_market_id"]=model_market; row["probability_bound_market_id"]=model_market; row["push_probability"]=float(model_output.get("push_p",0.0)); row["devig_method"]="MULTIPLICATIVE_V1" if spec.devig_class==MULTIPLICATIVE_2WAY else None
    if spec.entity_type==TEAM: row["probability_team_id"]=str(model_output.get("entity_id") or "")
    elif spec.entity_type in {BATTER,PITCHER}: row["probability_entity_id"]=str(model_output.get("entity_id") or "")
    elif spec.entity_type==MULTI_PITCHER:
        raw=str(model_output.get("entity_id") or ""); row["probability_entity_ids"]=raw.split("|") if raw else []
    if spec.threshold_semantics!=NO_THRESHOLD: row["probability_line"]=model_output.get("line")
    return row

def audit_status(market_id: str) -> str:
    spec=MARKET_BINDINGS.get(str(market_id).upper()); return "SPEC_MISSING" if spec is None else "PASS" if spec.production_wired else "UNAUDITABLE_IMPLICIT"

def settlement_pl(settlement: str, american_odds: Any, stake: Any) -> float:
    if settlement not in VALID_SETTLEMENTS: raise BindingError(f"ILLEGAL_SETTLEMENT:{settlement!r}")
    if settlement in {"PUSH","VOID","CANCELLED"}: return 0.0
    if isinstance(stake,bool) or not isinstance(stake,(int,float)) or not isfinite(float(stake)) or float(stake)<=0: raise BindingError(f"ILLEGAL_STAKE:{stake!r}")
    if settlement=="LOSS": return -float(stake)
    odds=_american(american_odds,"settlement"); mult=odds/100.0 if odds>0 else 100.0/abs(odds); return float(stake)*mult
