"""Formal, fail-closed MLB market binding contract for all 38 declared markets."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

TWO_WAY="TWO_WAY"; N_WAY="N_WAY"
FULL_GAME="FULL_GAME"; F5="F5"; FIRST_INNING="FIRST_INNING"
TEAM="TEAM"; BATTER="BATTER"; PITCHER="PITCHER"; GAME="GAME"; MULTI_PITCHER="MULTI_PITCHER"; FIELD="FIELD"
TEAM_BINDING="TeamBinding"; PLAYER_BINDING="PlayerBinding"; MULTI_ENTITY_BINDING="MultiEntityBinding"; NWAY_OUTCOME_BINDING="NWayOutcomeBinding"; GAME_BINDING="GameBinding"
_BINDING_TYPE_BY_ENTITY={TEAM:TEAM_BINDING,BATTER:PLAYER_BINDING,PITCHER:PLAYER_BINDING,MULTI_PITCHER:MULTI_ENTITY_BINDING,FIELD:NWAY_OUTCOME_BINDING,GAME:GAME_BINDING}

NO_THRESHOLD="NO_THRESHOLD"; INTEGER_PUSHABLE="INTEGER_PUSHABLE"; RUN_LINE_SIGNED="RUN_LINE_SIGNED"; HALF_POINT_ONLY="HALF_POINT_ONLY"
THRESHOLD_DOMAIN_NONE="NONE"; THRESHOLD_DOMAIN_NON_NEGATIVE="NON_NEGATIVE"; THRESHOLD_DOMAIN_RUN_LINE="RUN_LINE"
VALID_THRESHOLD_DOMAINS=frozenset({THRESHOLD_DOMAIN_NONE,THRESHOLD_DOMAIN_NON_NEGATIVE,THRESHOLD_DOMAIN_RUN_LINE})
MULTIPLICATIVE_2WAY="MULTIPLICATIVE_2WAY"; NWAY_UNAUTHORIZED="NWAY_UNAUTHORIZED"
SETTLE_GAME_RESULT="SETTLE_GAME_RESULT"; SETTLE_STAT_LINE="SETTLE_STAT_LINE"; SETTLE_ORDERING="SETTLE_ORDERING"; SETTLE_PITCHER_DECISION="SETTLE_PITCHER_DECISION"
VALID_SETTLEMENTS=("WIN","LOSS","PUSH","VOID","CANCELLED")

PAIR_SAME_TEAM="SAME_TEAM"; PAIR_OPPOSING_TEAMS="OPPOSING_TEAMS"; PAIR_OPPOSING_SIGNED="OPPOSING_SIGNED"; PAIR_SAME_GAME="SAME_GAME"; PAIR_SAME_PLAYER="SAME_PLAYER"; PAIR_SAME_PITCHER_PAIR="SAME_PITCHER_PAIR"; PAIR_WITHIN_MARKET="WITHIN_MARKET"; PAIR_UNSUPPORTED="UNSUPPORTED"
_PAIR_RULE={"MONEYLINE":PAIR_OPPOSING_TEAMS,"F5_MONEYLINE":PAIR_OPPOSING_TEAMS,"RUN_LINE":PAIR_OPPOSING_SIGNED,"F5_RUN_LINE":PAIR_OPPOSING_SIGNED,"TOTALS":PAIR_SAME_GAME,"F5_TOTALS":PAIR_SAME_GAME,"TEAM_TOTALS":PAIR_SAME_TEAM,"F5_TEAM_TOTALS":PAIR_SAME_TEAM,"NRFI":PAIR_WITHIN_MARKET,"YRFI":PAIR_WITHIN_MARKET,"FIRST_HOME_RUN":PAIR_UNSUPPORTED}

REQUIRED_QUOTE_IDENTITY=("event_id","game_number","book_key","retrieved_at","market_id","period","side","american_odds")
REQUIRED_PROBABILITY_IDENTITY=("probability_event_id","probability_market_id","probability_bound_market_id","probability_side")
_LEGAL_INCREMENTS=(0.0,0.5)
_DOMAIN_CEILING={"GAME_TOTAL":40.0,"TEAM_TOTAL":30.0,"BATTER_PROP":20.0,"PITCHER_PROP":40.0}

class BindingError(ValueError): pass

@dataclass(frozen=True)
class MarketBinding:
    market_id:str; family:str; ways:str; period:str; entity_type:str; sides:tuple; threshold_semantics:str; threshold_domain:str; devig_class:str; settlement_class:str; push_supported:bool; void_on_scratch:bool=False; void_on_lineup_absence:bool=False; requires_confirmed_lineup:bool=False; notes:str=""; production_wired:bool=False
    def __post_init__(self):
        if self.ways not in (TWO_WAY,N_WAY): raise BindingError(f"BAD_WAYS:{self.market_id}")
        if self.threshold_domain not in VALID_THRESHOLD_DOMAINS: raise BindingError(f"BAD_THRESHOLD_DOMAIN:{self.market_id}:{self.threshold_domain!r}")
        expected={NO_THRESHOLD:THRESHOLD_DOMAIN_NONE,RUN_LINE_SIGNED:THRESHOLD_DOMAIN_RUN_LINE,INTEGER_PUSHABLE:THRESHOLD_DOMAIN_NON_NEGATIVE,HALF_POINT_ONLY:THRESHOLD_DOMAIN_NON_NEGATIVE}.get(self.threshold_semantics)
        if expected is None or self.threshold_domain!=expected: raise BindingError(f"THRESHOLD_DOMAIN_SEMANTICS_MISMATCH:{self.market_id}:declared={self.threshold_domain}:expected={expected}")
        if self.push_supported and self.threshold_semantics==HALF_POINT_ONLY: raise BindingError(f"HALF_POINT_CANNOT_PUSH:{self.market_id}")
        if self.threshold_semantics==INTEGER_PUSHABLE and not self.push_supported: raise BindingError(f"INTEGER_LINE_MUST_SUPPORT_PUSH:{self.market_id}")
        if self.ways==N_WAY and self.devig_class==MULTIPLICATIVE_2WAY: raise BindingError(f"NWAY_THROUGH_TWO_WAY_DEVIG:{self.market_id}")

MARKET_BINDINGS={}
def _add(b):
    if b.market_id in MARKET_BINDINGS: raise BindingError(f"DUPLICATE_MARKET_ID:{b.market_id}")
    MARKET_BINDINGS[b.market_id]=b

def _ou(mid,family,entity,period=FULL_GAME,**kw):
    return MarketBinding(mid,family,TWO_WAY,period,entity,("OVER","UNDER"),INTEGER_PUSHABLE,THRESHOLD_DOMAIN_NON_NEGATIVE,MULTIPLICATIVE_2WAY,SETTLE_STAT_LINE,True,**kw)

_add(MarketBinding("MONEYLINE","GAME_LINE",TWO_WAY,FULL_GAME,TEAM,("HOME","AWAY"),NO_THRESHOLD,THRESHOLD_DOMAIN_NONE,MULTIPLICATIVE_2WAY,SETTLE_GAME_RESULT,False,production_wired=True))
_add(MarketBinding("RUN_LINE","GAME_LINE",TWO_WAY,FULL_GAME,TEAM,("HOME","AWAY"),RUN_LINE_SIGNED,THRESHOLD_DOMAIN_RUN_LINE,MULTIPLICATIVE_2WAY,SETTLE_GAME_RESULT,False,production_wired=True))
_add(MarketBinding("TOTALS","GAME_TOTAL",TWO_WAY,FULL_GAME,GAME,("OVER","UNDER"),INTEGER_PUSHABLE,THRESHOLD_DOMAIN_NON_NEGATIVE,MULTIPLICATIVE_2WAY,SETTLE_STAT_LINE,True,production_wired=True))
_add(MarketBinding("TEAM_TOTALS","TEAM_TOTAL",TWO_WAY,FULL_GAME,TEAM,("OVER","UNDER"),INTEGER_PUSHABLE,THRESHOLD_DOMAIN_NON_NEGATIVE,MULTIPLICATIVE_2WAY,SETTLE_STAT_LINE,True,production_wired=True))
_add(MarketBinding("F5_MONEYLINE","GAME_LINE",TWO_WAY,F5,TEAM,("HOME","AWAY"),NO_THRESHOLD,THRESHOLD_DOMAIN_NONE,MULTIPLICATIVE_2WAY,SETTLE_GAME_RESULT,True))
_add(MarketBinding("F5_RUN_LINE","GAME_LINE",TWO_WAY,F5,TEAM,("HOME","AWAY"),RUN_LINE_SIGNED,THRESHOLD_DOMAIN_RUN_LINE,MULTIPLICATIVE_2WAY,SETTLE_GAME_RESULT,False))
_add(MarketBinding("F5_TOTALS","GAME_TOTAL",TWO_WAY,F5,GAME,("OVER","UNDER"),INTEGER_PUSHABLE,THRESHOLD_DOMAIN_NON_NEGATIVE,MULTIPLICATIVE_2WAY,SETTLE_STAT_LINE,True))
_add(MarketBinding("F5_TEAM_TOTALS","TEAM_TOTAL",TWO_WAY,F5,TEAM,("OVER","UNDER"),INTEGER_PUSHABLE,THRESHOLD_DOMAIN_NON_NEGATIVE,MULTIPLICATIVE_2WAY,SETTLE_STAT_LINE,True))
_add(MarketBinding("NRFI","FIRST_INNING",TWO_WAY,FIRST_INNING,GAME,("YES","NO"),NO_THRESHOLD,THRESHOLD_DOMAIN_NONE,MULTIPLICATIVE_2WAY,SETTLE_STAT_LINE,False))
_add(MarketBinding("YRFI","FIRST_INNING",TWO_WAY,FIRST_INNING,GAME,("YES","NO"),NO_THRESHOLD,THRESHOLD_DOMAIN_NONE,MULTIPLICATIVE_2WAY,SETTLE_STAT_LINE,False))
for m in ("HITS","TOTAL_BASES","HOME_RUNS","RBI","RUNS","SINGLES","DOUBLES","TRIPLES","EXTRA_BASE_HITS","BATTER_BB","BATTER_K","STOLEN_BASES","HITS_RUNS_RBIS","RUNS_RBIS","HITS_STOLEN_BASES","HITS_RUNS_STOLEN_BASES","HITS_WALKS_STOLEN_BASES"):
    _add(_ou(m,"BATTER_PROP",BATTER,void_on_lineup_absence=True,requires_confirmed_lineup=True))
for m in ("PITCHER_K","PITCHER_OUTS","PITCHER_HITS_ALLOWED","PITCHER_BB","PITCHER_ER","PITCHER_HITS_WALKS_ER"):
    _add(_ou(m,"PITCHER_PROP",PITCHER,void_on_scratch=True))
for m in ("EITHER_PITCHER_HITS_ALLOWED","EITHER_PITCHER_BB","EITHER_PITCHER_ER"):
    _add(MarketBinding(m,"PITCHER_PROP",TWO_WAY,FULL_GAME,MULTI_PITCHER,("YES","NO"),INTEGER_PUSHABLE,THRESHOLD_DOMAIN_NON_NEGATIVE,MULTIPLICATIVE_2WAY,SETTLE_STAT_LINE,True,void_on_scratch=True))
_add(MarketBinding("FIRST_HOME_RUN","SPECIAL",N_WAY,FULL_GAME,FIELD,("PLAYER","NO_HOME_RUN"),NO_THRESHOLD,THRESHOLD_DOMAIN_NONE,NWAY_UNAUTHORIZED,SETTLE_ORDERING,False,requires_confirmed_lineup=True))
_add(MarketBinding("PITCHER_RECORD_WIN","SPECIAL",TWO_WAY,FULL_GAME,PITCHER,("YES","NO"),NO_THRESHOLD,THRESHOLD_DOMAIN_NONE,MULTIPLICATIVE_2WAY,SETTLE_PITCHER_DECISION,False,void_on_scratch=True))

def binding_type(market_id):
    spec=MARKET_BINDINGS.get(market_id)
    if spec is None: raise BindingError(f"UNKNOWN_MARKET_ID:{market_id!r}")
    return _BINDING_TYPE_BY_ENTITY[spec.entity_type]

def _require(row,field,mid):
    if field not in row or row[field] in (None,""): raise BindingError(f"MISSING_REQUIRED_FIELD:{mid}:{field}")
    return row[field]

def _valid_american(odds,mid):
    if isinstance(odds,bool) or not isinstance(odds,(int,float)): raise BindingError(f"PRICE_NOT_NUMERIC:{mid}:{odds!r}")
    o=float(odds)
    if o!=o or o in (float("inf"),float("-inf")): raise BindingError(f"PRICE_NOT_FINITE:{mid}:{odds!r}")
    if -100<o<100: raise BindingError(f"PRICE_INVALID_AMERICAN:{mid}:{o}")
    return o

def _tz_aware(v,field,mid):
    if not isinstance(v,datetime): raise BindingError(f"TIMESTAMP_NOT_DATETIME:{mid}:{field}:type={type(v).__name__}")
    if v.tzinfo is None or v.utcoffset() is None: raise BindingError(f"TIMESTAMP_NAIVE:{mid}:{field}")
    return v

def _quote_entity_validation(row,mid,spec,btype):
    side=row["side"]
    if btype==TEAM_BINDING:
        team=_require(row,"team_id",mid); home=_require(row,"event_home_team_id",mid); away=_require(row,"event_away_team_id",mid)
        if home==away: raise BindingError(f"EVENT_TEAMS_IDENTICAL:{mid}:{home!r}")
        if team not in {home,away}: raise BindingError(f"TEAM_NOT_IN_EVENT:{mid}:team_id={team}")
        if side in ("HOME","AWAY"):
            expected=home if side=="HOME" else away
            if team!=expected: raise BindingError(f"SIDE_TEAM_MISMATCH:{mid}:side={side}:team_id={team}:expected={expected}")
    elif btype in (PLAYER_BINDING,GAME_BINDING):
        ent=_require(row,"entity_id",mid)
        if btype==GAME_BINDING and str(ent)!=str(row["event_id"]): raise BindingError(f"GAME_ENTITY_EVENT_MISMATCH:{mid}:entity_id={ent}:event_id={row['event_id']}")
    elif btype==MULTI_ENTITY_BINDING:
        ids=row.get("entity_ids")
        if not isinstance(ids,(list,tuple)) or len(ids)!=2: raise BindingError(f"MULTI_ENTITY_REQUIRES_TWO_IDS:{mid}:got={ids!r}")
        if not all(str(x or "").strip() for x in ids): raise BindingError(f"MULTI_ENTITY_BLANK_ID:{mid}:{ids!r}")
        if len(set(ids))!=2: raise BindingError(f"MULTI_ENTITY_DUPLICATE_ID:{mid}:{ids!r}")
    elif btype==NWAY_OUTCOME_BINDING:
        outcome=_require(row,"outcome_id",mid)
        if side=="PLAYER" and not str(row.get("outcome_player_id") or "").strip(): raise BindingError(f"NWAY_PLAYER_OUTCOME_REQUIRES_PLAYER_ID:{mid}")
        if side=="NO_HOME_RUN" and outcome!="NO_HOME_RUN": raise BindingError(f"NWAY_NO_HR_CANONICAL_OUTCOME_MISMATCH:{mid}:{outcome!r}")

def _quote_threshold_validation(row,mid,spec):
    line=row.get("line")
    if spec.threshold_semantics==NO_THRESHOLD:
        if line not in (None,""): raise BindingError(f"UNEXPECTED_THRESHOLD:{mid}:line={line!r}")
        return
    if spec.threshold_semantics==RUN_LINE_SIGNED:
        if line not in (1.5,-1.5): raise BindingError(f"ILLEGAL_RUN_LINE:{mid}:line={line!r}:expected +/-1.5")
        return
    if isinstance(line,bool) or not isinstance(line,(int,float)): raise BindingError(f"THRESHOLD_NOT_NUMERIC:{mid}:line={line!r}")
    f=float(line)
    if f!=f or f in (float("inf"),float("-inf")): raise BindingError(f"THRESHOLD_NOT_FINITE:{mid}:line={line!r}")
    if round(abs(f)%1.0,6) not in _LEGAL_INCREMENTS: raise BindingError(f"ILLEGAL_THRESHOLD_INCREMENT:{mid}:line={line}")
    if spec.threshold_domain==THRESHOLD_DOMAIN_NON_NEGATIVE and f<0: raise BindingError(f"THRESHOLD_OUT_OF_DOMAIN:{mid}:line={line}")
    ceiling=_DOMAIN_CEILING.get(spec.family)
    if ceiling is not None and f>ceiling: raise BindingError(f"THRESHOLD_ABOVE_DOMAIN_CEILING:{mid}:line={line}:ceiling={ceiling}")

def validate_quote_binding(row:Mapping[str,Any])->None:
    mid=str(row.get("market_id") or ""); spec=MARKET_BINDINGS.get(mid)
    if spec is None: raise BindingError(f"UNKNOWN_MARKET_ID:{mid!r}")
    for f in REQUIRED_QUOTE_IDENTITY:_require(row,f,mid)
    _valid_american(row["american_odds"],mid); _tz_aware(row["retrieved_at"],"retrieved_at",mid)
    gn=row["game_number"]
    if isinstance(gn,bool) or not isinstance(gn,int) or gn not in (1,2): raise BindingError(f"ILLEGAL_GAME_NUMBER:{mid}:{gn!r}:MLB game_number is 1 or 2")
    if row["period"]!=spec.period: raise BindingError(f"PERIOD_MISMATCH:{mid}:got={row['period']}:expected={spec.period}")
    if row["side"] not in spec.sides: raise BindingError(f"ILLEGAL_SIDE:{mid}:side={row['side']!r}:legal={spec.sides}")
    if row.get("entity_type") and row["entity_type"]!=spec.entity_type: raise BindingError(f"ENTITY_TYPE_MISMATCH:{mid}")
    _quote_entity_validation(row,mid,spec,_BINDING_TYPE_BY_ENTITY[spec.entity_type]); _quote_threshold_validation(row,mid,spec)

def validate_binding(row:Mapping[str,Any])->None:
    validate_quote_binding(row); mid=str(row["market_id"]); spec=MARKET_BINDINGS[mid]; btype=_BINDING_TYPE_BY_ENTITY[spec.entity_type]
    expected={"probability_event_id":str(row["event_id"]),"probability_market_id":mid,"probability_bound_market_id":mid,"probability_side":row["side"]}
    for f in REQUIRED_PROBABILITY_IDENTITY:
        v=_require(row,f,mid)
        if str(v)!=str(expected[f]): raise BindingError(f"{f.upper()}_MISMATCH:{mid}:got={v!r}:expected={expected[f]!r}")
    if btype==TEAM_BINDING:
        if str(_require(row,"probability_team_id",mid))!=str(row["team_id"]): raise BindingError(f"PROBABILITY_TEAM_MISMATCH:{mid}")
    elif btype in (PLAYER_BINDING,GAME_BINDING):
        if str(_require(row,"probability_entity_id",mid))!=str(row["entity_id"]): raise BindingError(f"PROBABILITY_ENTITY_MISMATCH:{mid}")
    elif btype==MULTI_ENTITY_BINDING:
        pids=_require(row,"probability_entity_ids",mid)
        if tuple(map(str,pids))!=tuple(map(str,row["entity_ids"])): raise BindingError(f"MULTI_ENTITY_PROBABILITY_MISMATCH:{mid}")
    elif btype==NWAY_OUTCOME_BINDING:
        if str(_require(row,"probability_outcome_id",mid))!=str(row["outcome_id"]): raise BindingError(f"NWAY_PROBABILITY_OUTCOME_MISMATCH:{mid}")
        if row["side"]=="PLAYER" and str(_require(row,"probability_outcome_player_id",mid))!=str(row["outcome_player_id"]): raise BindingError(f"NWAY_PROBABILITY_PLAYER_MISMATCH:{mid}")
    if spec.threshold_semantics!=NO_THRESHOLD:
        pl=_require(row,"probability_line",mid)
        if float(pl)!=float(row["line"]): raise BindingError(f"PROBABILITY_THRESHOLD_MISMATCH:{mid}:price_line={row['line']}:probability_line={pl}")
    push=_require(row,"push_probability",mid)
    if isinstance(push,bool) or not isinstance(push,(int,float)): raise BindingError(f"PUSH_PROBABILITY_NOT_NUMERIC:{mid}:{push!r}")
    push=float(push)
    if push!=push or not 0<=push<=1: raise BindingError(f"PUSH_PROBABILITY_OUT_OF_RANGE:{mid}:{push!r}")
    line=row.get("line")
    if isinstance(line,(int,float)) and not isinstance(line,bool) and abs(float(line)*2)%2==1 and push>0: raise BindingError(f"HALF_POINT_GIVEN_PUSH_MASS:{mid}:line={line}:push={push}")
    if push>0 and not spec.push_supported: raise BindingError(f"PUSH_NOT_SUPPORTED:{mid}:push={push}")
    devig=row.get("devig_method")
    if spec.devig_class==NWAY_UNAUTHORIZED and devig: raise BindingError(f"NWAY_DEVIG_UNAUTHORIZED:{mid}:method={devig}")
    if devig and spec.devig_class==MULTIPLICATIVE_2WAY and devig!="MULTIPLICATIVE_V1": raise BindingError(f"UNAPPROVED_DEVIG_METHOD:{mid}:{devig}")
    st=row.get("settlement")
    if st is not None and st not in VALID_SETTLEMENTS: raise BindingError(f"ILLEGAL_SETTLEMENT:{mid}:{st!r}")
    if st=="PUSH" and not spec.push_supported: raise BindingError(f"PUSH_SETTLEMENT_ON_NON_PUSHABLE:{mid}")

def validate_paired_quote(a:Mapping[str,Any],b:Mapping[str,Any],max_skew_seconds:float=30.0)->None:
    validate_quote_binding(a); validate_quote_binding(b); mid=a["market_id"]
    if b["market_id"]!=mid: raise BindingError(f"PAIRED_QUOTE_MARKET_MISMATCH:{mid}!={b['market_id']}")
    for k in ("book_key","event_id","game_number","period"):
        if a.get(k)!=b.get(k): raise BindingError(f"PAIRED_QUOTE_MISMATCH:{k}:{a.get(k)!r}!={b.get(k)!r}")
    if a["side"]==b["side"]: raise BindingError("PAIRED_QUOTE_SAME_SIDE")
    rule=_PAIR_RULE.get(mid,PAIR_SAME_PLAYER if _BINDING_TYPE_BY_ENTITY[MARKET_BINDINGS[mid].entity_type]==PLAYER_BINDING else PAIR_SAME_PITCHER_PAIR)
    if rule==PAIR_UNSUPPORTED: raise BindingError(f"PAIRED_QUOTE_UNSUPPORTED:{mid}")
    if rule in (PAIR_OPPOSING_TEAMS,PAIR_OPPOSING_SIGNED):
        if {a["side"],b["side"]}!={"HOME","AWAY"}: raise BindingError(f"PAIRED_QUOTE_SIDES_NOT_HOME_AWAY:{mid}")
        if str(a["team_id"])==str(b["team_id"]): raise BindingError(f"PAIRED_QUOTE_SAME_TEAM_ON_OPPOSING_MARKET:{mid}")
        teams={str(a["event_home_team_id"]),str(a["event_away_team_id"])}
        if {str(a["team_id"]),str(b["team_id"])}!=teams: raise BindingError(f"PAIRED_QUOTE_TEAMS_NOT_EVENT_TEAMS:{mid}")
        if rule==PAIR_OPPOSING_SIGNED and float(a["line"])!=-float(b["line"]): raise BindingError(f"PAIRED_QUOTE_RUN_LINE_NOT_OPPOSITE:{mid}")
        if rule==PAIR_OPPOSING_TEAMS and (a.get("line") not in (None,"") or b.get("line") not in (None,"")): raise BindingError(f"PAIRED_QUOTE_UNEXPECTED_LINE:{mid}")
    else:
        if a.get("line")!=b.get("line"): raise BindingError("PAIRED_QUOTE_MISMATCH:line")
        if rule==PAIR_SAME_TEAM and str(a.get("team_id"))!=str(b.get("team_id")): raise BindingError(f"PAIRED_QUOTE_TEAM_MISMATCH:{mid}")
        if rule in (PAIR_SAME_GAME,PAIR_SAME_PLAYER) and str(a.get("entity_id"))!=str(b.get("entity_id")): raise BindingError(f"PAIRED_QUOTE_ENTITY_MISMATCH:{mid}")
        if rule==PAIR_SAME_PITCHER_PAIR and tuple(a.get("entity_ids") or ())!=tuple(b.get("entity_ids") or ()): raise BindingError(f"PAIRED_QUOTE_PITCHER_PAIR_MISMATCH:{mid}")
    skew=abs((a["retrieved_at"]-b["retrieved_at"]).total_seconds())
    if skew>max_skew_seconds: raise BindingError(f"PAIRED_QUOTE_SKEW_EXCEEDED:{skew:.1f}s>{max_skew_seconds}s")

def settlement_pl(settlement,american_odds,stake):
    if settlement not in VALID_SETTLEMENTS: raise BindingError(f"ILLEGAL_SETTLEMENT:{settlement!r}")
    if settlement in ("PUSH","VOID","CANCELLED"): return 0.0
    if isinstance(stake,bool) or not isinstance(stake,(int,float)) or stake!=stake or stake<=0: raise BindingError(f"ILLEGAL_STAKE:{stake!r}")
    if settlement=="LOSS": return -abs(stake)
    o=_valid_american(american_odds,"settlement"); profit=o/100 if o>0 else 100/abs(o); return abs(stake)*profit

def audit_status(market_id):
    spec=MARKET_BINDINGS.get(market_id)
    if spec is None:return "SPEC_MISSING"
    return "PASS" if spec.production_wired else "UNAUDITABLE_IMPLICIT"
