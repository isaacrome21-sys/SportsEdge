"""Fail-closed MLB game-market acquisition from The Odds API.

Acquires DraftKings h2h, spreads, totals, and first-inning total runs and binds
every provider event to exactly one MLB StatsAPI game before emitting SportsEdge
quotes. This module is price acquisition only: sportsbook prices never become
Model_P.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Iterable, Mapping
from urllib.request import urlopen

from .mlb_source import GameSnapshot
from .odds_api_source import (
    DEFAULT_BOOKMAKERS,
    DEFAULT_TTL_SECONDS,
    OddsApiSourceError,
    _event_url,
    _get_json,
    bind_provider_event,
    normalize_name,
)
from .runtime import parse_timestamp

GAME_MARKETS = ("h2h", "spreads", "totals")
FIRST_INNING_TOTAL_MARKET_KEY = "totals_1st_1_innings"

@dataclass(frozen=True)
class GameOddsSnapshot:
    quotes: tuple[dict[str, Any], ...]
    failures: tuple[dict[str, Any], ...]

def _team_side(name: Any, game: GameSnapshot) -> str:
    key = normalize_name(name)
    if key == normalize_name(game.home_name): return "HOME"
    if key == normalize_name(game.away_name): return "AWAY"
    raise OddsApiSourceError("ODDS_GAME_TEAM_UNRESOLVED")

def _updated(market: Mapping[str, Any], bookmaker: Mapping[str, Any]) -> datetime:
    value = market.get("last_update") or bookmaker.get("last_update")
    try: return parse_timestamp(value)
    except Exception as exc: raise OddsApiSourceError("ODDS_MARKET_TIMESTAMP_INVALID") from exc

def parse_first_inning_odds(payload: Mapping[str, Any], *, game: GameSnapshot, market_key: str = FIRST_INNING_TOTAL_MARKET_KEY, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> GameOddsSnapshot:
    if not isinstance(market_key, str) or not market_key.strip(): raise OddsApiSourceError("FIRST_INNING_MARKET_KEY_REQUIRED")
    quotes=[]; failures=[]
    if not isinstance(payload, Mapping): return GameOddsSnapshot((), ({"reason":"ODDS_EVENT_ODDS_MALFORMED","game_id":str(game.game_pk)},))
    for bookmaker in payload.get("bookmakers") or []:
        if not isinstance(bookmaker, Mapping): failures.append({"reason":"ODDS_BOOKMAKER_MALFORMED","game_id":str(game.game_pk)}); continue
        book_key=str(bookmaker.get("key") or "").strip(); book_title=str(bookmaker.get("title") or book_key).strip()
        for market in bookmaker.get("markets") or []:
            if not isinstance(market, Mapping): failures.append({"reason":"ODDS_MARKET_MALFORMED","game_id":str(game.game_pk),"book_key":book_key}); continue
            mk=str(market.get("key") or "").strip()
            if mk != market_key: continue
            try: retrieved_at=_updated(market, bookmaker)
            except Exception as exc: failures.append({"reason":str(exc),"game_id":str(game.game_pk),"book_key":book_key,"raw_market_name":mk}); continue
            for outcome in market.get("outcomes") or []:
                try:
                    if not isinstance(outcome, Mapping): raise OddsApiSourceError("ODDS_OUTCOME_MALFORMED")
                    price=outcome.get("price"); point=outcome.get("point")
                    if price is None: raise OddsApiSourceError("ODDS_OUTCOME_PRICE_MISSING")
                    if point is None: raise OddsApiSourceError("ODDS_OUTCOME_LINE_MISSING")
                    if float(point) != 0.5: raise OddsApiSourceError("FIRST_INNING_LINE_NOT_HALF_RUN")
                    raw_side=str(outcome.get("name") or "").upper()
                    if raw_side not in {"OVER","UNDER"}: raise OddsApiSourceError("ODDS_SIDE_UNSUPPORTED")
                    canonical_market="YRFI" if raw_side=="OVER" else "NRFI"
                    base={"game_id":str(game.game_pk),"period":"1ST","book_key":book_key,"sportsbook":book_title,"retrieved_at":retrieved_at,"ttl_seconds":ttl_seconds,"american_odds":price,"raw_market_name":mk,"away_team":str(game.away_name),"home_team":str(game.home_name),"is_alternate":False}
                    quotes.append({**base,"market":canonical_market,"side":raw_side,"selection":canonical_market,"line":0.5})
                except Exception as exc:
                    failures.append({"reason":str(exc),"game_id":str(game.game_pk),"book_key":book_key,"raw_market_name":mk})
    return GameOddsSnapshot(tuple(quotes), tuple(failures))

def parse_game_event_odds(payload: Mapping[str, Any], *, game: GameSnapshot, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> GameOddsSnapshot:
    quotes=[]; failures=[]
    if not isinstance(payload, Mapping): return GameOddsSnapshot((), ({"reason":"ODDS_EVENT_ODDS_MALFORMED","game_id":str(game.game_pk)},))
    for bookmaker in payload.get("bookmakers") or []:
        if not isinstance(bookmaker, Mapping): failures.append({"reason":"ODDS_BOOKMAKER_MALFORMED","game_id":str(game.game_pk)}); continue
        book_key=str(bookmaker.get("key") or "").strip(); book_title=str(bookmaker.get("title") or book_key).strip()
        for market in bookmaker.get("markets") or []:
            if not isinstance(market, Mapping): failures.append({"reason":"ODDS_MARKET_MALFORMED","game_id":str(game.game_pk),"book_key":book_key}); continue
            market_key=str(market.get("key") or "").strip()
            if market_key not in GAME_MARKETS: continue
            try: retrieved_at=_updated(market, bookmaker)
            except Exception as exc: failures.append({"reason":str(exc),"game_id":str(game.game_pk),"book_key":book_key,"raw_market_name":market_key}); continue
            for outcome in market.get("outcomes") or []:
                try:
                    if not isinstance(outcome, Mapping): raise OddsApiSourceError("ODDS_OUTCOME_MALFORMED")
                    price=outcome.get("price")
                    if price is None: raise OddsApiSourceError("ODDS_OUTCOME_PRICE_MISSING")
                    base={"game_id":str(game.game_pk),"period":"FG","book_key":book_key,"sportsbook":book_title,"retrieved_at":retrieved_at,"ttl_seconds":ttl_seconds,"american_odds":price,"raw_market_name":market_key,"away_team":str(game.away_name),"home_team":str(game.home_name),"is_alternate":False}
                    if market_key=="h2h":
                        side=_team_side(outcome.get("name"),game); quotes.append({**base,"market":"MONEYLINE","side":side,"selection":str(outcome.get("name") or "").strip(),"line":None})
                    elif market_key=="spreads":
                        side=_team_side(outcome.get("name"),game); point=outcome.get("point")
                        if point is None: raise OddsApiSourceError("ODDS_OUTCOME_LINE_MISSING")
                        quotes.append({**base,"market":"RUN_LINE","side":side,"selection":str(outcome.get("name") or "").strip(),"line":point})
                    else:
                        side=str(outcome.get("name") or "").upper()
                        if side not in {"OVER","UNDER"}: raise OddsApiSourceError("ODDS_SIDE_UNSUPPORTED")
                        point=outcome.get("point")
                        if point is None: raise OddsApiSourceError("ODDS_OUTCOME_LINE_MISSING")
                        quotes.append({**base,"market":"TOTALS","side":side,"selection":side.title(),"line":point})
                except Exception as exc:
                    failures.append({"reason":str(exc),"game_id":str(game.game_pk),"book_key":book_key,"raw_market_name":market_key})
    return GameOddsSnapshot(tuple(quotes), tuple(failures))

def fetch_mlb_game_quotes(*, api_key: str, schedule: Iterable[GameSnapshot], opener: Callable=urlopen, bookmakers: Iterable[str]=DEFAULT_BOOKMAKERS, ttl_seconds: int=DEFAULT_TTL_SECONDS) -> GameOddsSnapshot:
    games=list(schedule); requested_books=",".join(str(x).strip() for x in bookmakers if str(x).strip())
    if not requested_books: raise OddsApiSourceError("ODDS_BOOKMAKERS_MISSING")
    url=_event_url("/sports/baseball_mlb/odds", api_key=api_key, params={"regions":"us","bookmakers":requested_books,"markets":",".join(GAME_MARKETS),"oddsFormat":"american","dateFormat":"iso","includeSids":"true"})
    payload=_get_json(url, opener=opener, label="game-markets")
    if not isinstance(payload,list): raise OddsApiSourceError("ODDS_GAME_MARKETS_RESPONSE_NOT_LIST")
    quotes=[]; failures=[]
    for event in payload:
        try:
            game=bind_provider_event(event,games); snap=parse_game_event_odds(event,game=game,ttl_seconds=ttl_seconds); quotes.extend(snap.quotes); failures.extend(snap.failures)
        except Exception as exc: failures.append({"reason":str(exc),"provider_event_id":str(event.get("id") if isinstance(event,Mapping) else "")})
    return GameOddsSnapshot(tuple(quotes),tuple(failures))

def fetch_event_first_inning_quotes(*, api_key: str, provider_event_id: str, game: GameSnapshot, opener: Callable=urlopen, bookmakers: Iterable[str]=DEFAULT_BOOKMAKERS, ttl_seconds: int=DEFAULT_TTL_SECONDS) -> GameOddsSnapshot:
    requested_books=",".join(str(x).strip() for x in bookmakers if str(x).strip())
    if not requested_books: raise OddsApiSourceError("ODDS_BOOKMAKERS_MISSING")
    eid=str(provider_event_id or "").strip()
    if not eid: raise OddsApiSourceError("ODDS_PROVIDER_EVENT_ID_MISSING")
    url=_event_url(f"/sports/baseball_mlb/events/{eid}/odds",api_key=api_key,params={"regions":"us","bookmakers":requested_books,"markets":FIRST_INNING_TOTAL_MARKET_KEY,"oddsFormat":"american","dateFormat":"iso","includeSids":"true"})
    payload=_get_json(url,opener=opener,label="first-inning-market")
    if not isinstance(payload,Mapping): raise OddsApiSourceError("ODDS_FIRST_INNING_RESPONSE_NOT_OBJECT")
    return parse_first_inning_odds(payload,game=game,ttl_seconds=ttl_seconds)

def fetch_event_market_keys(*, api_key: str, provider_event_id: str, opener: Callable=urlopen) -> set[str]:
    eid=str(provider_event_id or "").strip()
    if not eid: raise OddsApiSourceError("ODDS_PROVIDER_EVENT_ID_MISSING")
    url=_event_url(f"/sports/baseball_mlb/events/{eid}/markets",api_key=api_key,params={})
    payload=_get_json(url,opener=opener,label="event-market-discovery")
    bookmakers=(payload.get("bookmakers") or []) if isinstance(payload,Mapping) else payload if isinstance(payload,list) else None
    if bookmakers is None: raise OddsApiSourceError("ODDS_EVENT_MARKETS_RESPONSE_MALFORMED")
    keys=set()
    for bookmaker in bookmakers:
        if not isinstance(bookmaker,Mapping): continue
        for market in bookmaker.get("markets") or []:
            key=str((market.get("key") if isinstance(market,Mapping) else market) or "").strip()
            if key: keys.add(key)
    return keys

def first_inning_market_availability(*, api_key: str, provider_event_id: str, opener: Callable=urlopen) -> str:
    keys=fetch_event_market_keys(api_key=api_key,provider_event_id=provider_event_id,opener=opener)
    return "MARKET_AVAILABLE" if FIRST_INNING_TOTAL_MARKET_KEY in keys else "LEGITIMATE_MARKET_UNAVAILABLE"

def fetch_mlb_first_inning_quotes(*, api_key: str, schedule: Iterable[GameSnapshot], opener: Callable=urlopen, bookmakers: Iterable[str]=DEFAULT_BOOKMAKERS, ttl_seconds: int=DEFAULT_TTL_SECONDS) -> GameOddsSnapshot:
    """Acquire YRFI/NRFI for every uniquely bound MLB event, fail-closed per event."""
    games=list(schedule)
    events_url=_event_url("/sports/baseball_mlb/events",api_key=api_key,params={})
    events=_get_json(events_url,opener=opener,label="game-events-first-inning")
    if not isinstance(events,list): raise OddsApiSourceError("ODDS_EVENTS_RESPONSE_NOT_LIST")
    quotes=[]; failures=[]
    for event in events:
        try:
            game=bind_provider_event(event,games); eid=str(event.get("id") or "").strip()
            if not eid: raise OddsApiSourceError("ODDS_EVENT_ID_MISSING")
            availability=first_inning_market_availability(api_key=api_key,provider_event_id=eid,opener=opener)
            if availability != "MARKET_AVAILABLE":
                failures.append({"reason":"LEGITIMATE_MARKET_UNAVAILABLE","game_id":str(game.game_pk),"provider_event_id":eid,"market":FIRST_INNING_TOTAL_MARKET_KEY}); continue
            snap=fetch_event_first_inning_quotes(api_key=api_key,provider_event_id=eid,game=game,opener=opener,bookmakers=bookmakers,ttl_seconds=ttl_seconds)
            quotes.extend(snap.quotes); failures.extend(snap.failures)
        except Exception as exc:
            failures.append({"reason":str(exc),"provider_event_id":str(event.get("id") if isinstance(event,Mapping) else "")})
    return GameOddsSnapshot(tuple(quotes),tuple(failures))

def fetch_all_mlb_game_quotes(*, api_key: str, schedule: Iterable[GameSnapshot], opener: Callable=urlopen, bookmakers: Iterable[str]=DEFAULT_BOOKMAKERS, ttl_seconds: int=DEFAULT_TTL_SECONDS) -> GameOddsSnapshot:
    games=list(schedule)
    fg=fetch_mlb_game_quotes(api_key=api_key,schedule=games,opener=opener,bookmakers=bookmakers,ttl_seconds=ttl_seconds)
    fi=fetch_mlb_first_inning_quotes(api_key=api_key,schedule=games,opener=opener,bookmakers=bookmakers,ttl_seconds=ttl_seconds)
    return GameOddsSnapshot(tuple(fg.quotes)+tuple(fi.quotes), tuple(fg.failures)+tuple(fi.failures))
