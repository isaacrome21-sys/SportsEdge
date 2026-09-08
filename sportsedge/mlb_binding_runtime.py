"""Production adapter from normalized MLB quotes + official LiveGame identity to binding V1.2.2.

Sportsbook identity is captured at acquisition/quote normalization and is never
back-filled from model input. Official MLB event context is an independent binding
source used to reject mismatches. Model readout identity contains only the market
readout request needed to prove Model_P was calculated for the same offer semantics.
"""
from __future__ import annotations
from typing import Any, Mapping
from .mlb_market_binding import (
    BindingError,
    GAME_BINDING,
    MARKET_BINDINGS,
    NO_THRESHOLD,
    TEAM_BINDING,
    _BINDING_TYPE_BY_ENTITY,
)

WIRED_MARKETS=frozenset({"MONEYLINE","RUN_LINE","TOTALS","TEAM_TOTALS"})
_PERIOD_MAP={"FG":"FULL_GAME","FULL_GAME":"FULL_GAME","F5":"F5","5":"F5","1ST":"FIRST_INNING","1":"FIRST_INNING","FIRST_INNING":"FIRST_INNING"}
_SIDE_MAP={"HOME_ML":"HOME","AWAY_ML":"AWAY","HOME_RL":"HOME","AWAY_RL":"AWAY"}
_SOURCE_IDENTITY_FIELDS=("event_id","game_number","event_home_team_id","event_away_team_id","book_key")


def _canonical_side(value:Any)->str:
    side=str(value or "").upper(); return _SIDE_MAP.get(side,side)


def _canonical_period(value:Any)->str:
    period=str(value or "").upper(); return _PERIOD_MAP.get(period,period)


def _required_source(quote:Mapping[str,Any],field:str,mid:str)->Any:
    value=quote.get(field)
    if value in (None,""):
        raise BindingError(f"MISSING_SOURCE_BINDING_IDENTITY:{mid}:{field}")
    return value


def _validate_source_against_official(*,game:Any,quote:Mapping[str,Any],mid:str)->tuple[str,int,str,str]:
    for field in _SOURCE_IDENTITY_FIELDS:
        _required_source(quote,field,mid)
    event_id=str(quote["event_id"])
    home=str(quote["event_home_team_id"])
    away=str(quote["event_away_team_id"])
    game_number=quote["game_number"]
    if isinstance(game_number,bool) or not isinstance(game_number,int):
        raise BindingError(f"ILLEGAL_GAME_NUMBER:{mid}:{game_number!r}")
    official_event=str(game.game_pk)
    official_home=str(game.home_team_id)
    official_away=str(game.away_team_id)
    official_number=getattr(game,"game_number",None)
    if official_number is None:
        raise BindingError(f"OFFICIAL_GAME_NUMBER_MISSING:{mid}")
    if event_id!=official_event:
        raise BindingError(f"SOURCE_EVENT_MISMATCH:{mid}:quote={event_id}:official={official_event}")
    if game_number!=int(official_number):
        raise BindingError(f"SOURCE_GAME_NUMBER_MISMATCH:{mid}:quote={game_number}:official={official_number}")
    if home!=official_home or away!=official_away:
        raise BindingError(
            f"SOURCE_TEAM_ID_MISMATCH:{mid}:quote={away}@{home}:official={official_away}@{official_home}"
        )
    if home==away:
        raise BindingError(f"EVENT_TEAMS_IDENTICAL:{mid}:{home}")
    return event_id,game_number,home,away


def quote_binding_row(*,game:Any,quote:Mapping[str,Any])->dict[str,Any]:
    mid=str(quote.get("market") or "").upper()
    if mid not in WIRED_MARKETS:
        raise BindingError(f"MLB_BINDING_MARKET_NOT_WIRED:{mid}")
    spec=MARKET_BINDINGS[mid]
    event_id,game_number,home,away=_validate_source_against_official(game=game,quote=quote,mid=mid)
    if str(quote.get("game_id"))!=str(game.game_pk):
        raise BindingError(f"MLB_ROUTING_GAME_MISMATCH:{mid}:route={quote.get('game_id')}:official={game.game_pk}")
    line=quote.get("line")
    if spec.threshold_semantics==NO_THRESHOLD:
        line=None
    row={
        "event_id":event_id,
        "game_number":game_number,
        "book_key":quote.get("book_key"),
        "retrieved_at":quote.get("retrieved_at"),
        "market_id":mid,
        "period":_canonical_period(quote.get("period")),
        "side":_canonical_side(quote.get("side")),
        "american_odds":quote.get("american_odds"),
        "line":line,
    }
    btype=_BINDING_TYPE_BY_ENTITY[spec.entity_type]
    if btype==TEAM_BINDING:
        row.update(
            team_id=str(quote.get("entity_id") or ""),
            event_home_team_id=home,
            event_away_team_id=away,
        )
    elif btype==GAME_BINDING:
        row["entity_id"]=str(quote.get("entity_id") or "")
    else:
        row["entity_id"]=str(quote.get("entity_id") or "")
    return row


def probability_binding_row(*,game:Any,quote:Mapping[str,Any],readout_request:Mapping[str,Any],push_probability:float)->dict[str,Any]:
    """Attach probability semantics without importing sportsbook identity into the model.

    ``readout_request`` is the orchestration request that selected a probability from
    the model distribution. It intentionally has no event/book/canonical-team fields.
    """
    forbidden={"event_id","game_number","book_key","event_home_team_id","event_away_team_id"}.intersection(readout_request)
    if forbidden:
        raise BindingError(f"READOUT_REQUEST_CONTAINS_SOURCE_IDENTITY:{sorted(forbidden)}")
    row=quote_binding_row(game=game,quote=quote)
    mid=row["market_id"]
    spec=MARKET_BINDINGS[mid]
    request_mid=str(readout_request.get("market") or "").upper()
    request_side=_canonical_side(readout_request.get("side"))
    request_entity=str(readout_request.get("entity_id") or "")
    row.update(
        probability_event_id=str(game.game_pk),
        probability_market_id=request_mid,
        probability_bound_market_id=request_mid,
        probability_side=request_side,
        push_probability=push_probability,
        devig_method="MULTIPLICATIVE_V1",
    )
    btype=_BINDING_TYPE_BY_ENTITY[spec.entity_type]
    if btype==TEAM_BINDING:
        row["probability_team_id"]=request_entity
    else:
        row["probability_entity_id"]=request_entity
    if spec.threshold_semantics!=NO_THRESHOLD:
        row["probability_line"]=readout_request.get("line")
    return row
