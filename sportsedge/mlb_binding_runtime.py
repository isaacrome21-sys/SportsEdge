"""Production adapter from normalized MLB quotes + official LiveGame identity to binding V1.2.1.

Sportsbook identity is stamped at the quote/orchestration boundary. Model probability
identity is added only after inference from the exact model_input that produced Model_P.
"""
from __future__ import annotations
from typing import Any, Mapping
from .mlb_market_binding import GAME_BINDING, MARKET_BINDINGS, NO_THRESHOLD, TEAM_BINDING, _BINDING_TYPE_BY_ENTITY

WIRED_MARKETS=frozenset({"MONEYLINE","RUN_LINE","TOTALS","TEAM_TOTALS"})
_PERIOD_MAP={"FG":"FULL_GAME","FULL_GAME":"FULL_GAME","F5":"F5","5":"F5","1ST":"FIRST_INNING","1":"FIRST_INNING","FIRST_INNING":"FIRST_INNING"}
_SIDE_MAP={"HOME_ML":"HOME","AWAY_ML":"AWAY","HOME_RL":"HOME","AWAY_RL":"AWAY"}

def _canonical_side(value:Any)->str:
    side=str(value or "").upper(); return _SIDE_MAP.get(side,side)

def _canonical_period(value:Any)->str:
    period=str(value or "").upper(); return _PERIOD_MAP.get(period,period)

def quote_binding_row(*,game:Any,quote:Mapping[str,Any])->dict[str,Any]:
    mid=str(quote.get("market") or "").upper()
    if mid not in WIRED_MARKETS: raise ValueError(f"MLB_BINDING_MARKET_NOT_WIRED:{mid}")
    spec=MARKET_BINDINGS[mid]; event_id=str(game.game_pk)
    if str(quote.get("game_id"))!=event_id: raise ValueError(f"MLB_BINDING_QUOTE_EVENT_MISMATCH:quote={quote.get('game_id')}:official={event_id}")
    line=quote.get("line")
    if spec.threshold_semantics==NO_THRESHOLD: line=None
    row={"event_id":event_id,"game_number":game.game_number,"book_key":quote.get("book_key"),"retrieved_at":quote.get("retrieved_at"),"market_id":mid,"period":_canonical_period(quote.get("period")),"side":_canonical_side(quote.get("side")),"american_odds":quote.get("american_odds"),"line":line}
    btype=_BINDING_TYPE_BY_ENTITY[spec.entity_type]
    if btype==TEAM_BINDING:
        row.update(team_id=str(quote.get("entity_id") or ""),event_home_team_id=str(game.home_team_id),event_away_team_id=str(game.away_team_id))
    elif btype==GAME_BINDING:
        row["entity_id"]=str(quote.get("entity_id") or "")
    else:
        row["entity_id"]=str(quote.get("entity_id") or "")
    return row

def probability_binding_row(*,game:Any,quote:Mapping[str,Any],model_input:Mapping[str,Any],push_probability:float)->dict[str,Any]:
    row=quote_binding_row(game=game,quote=quote); mid=row["market_id"]; spec=MARKET_BINDINGS[mid]
    model_mid=str(model_input.get("market") or "").upper(); model_event=str(model_input.get("game_id") or ""); model_side=_canonical_side(model_input.get("side")); model_entity=str(model_input.get("entity_id") or "")
    row.update(probability_event_id=model_event,probability_market_id=model_mid,probability_bound_market_id=model_mid,probability_side=model_side,push_probability=push_probability,devig_method="MULTIPLICATIVE_V1")
    btype=_BINDING_TYPE_BY_ENTITY[spec.entity_type]
    if btype==TEAM_BINDING: row["probability_team_id"]=model_entity
    else: row["probability_entity_id"]=model_entity
    if spec.threshold_semantics!=NO_THRESHOLD: row["probability_line"]=model_input.get("line")
    return row
