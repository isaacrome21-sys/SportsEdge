"""Fully automated MLB slate orchestration with fail-closed live-source guards.

The runner acquires MLB schedule/boxscore state directly and consumes configured
HTTP JSON snapshots for sportsbook quotes, model feature source facts, and
(optional) projected lineups. It never invents missing prices, features, teams,
or lineups and never derives Model_P from sportsbook prices.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from math import isfinite
from typing import Any, Callable, Mapping
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .feature_bridge import FeatureBridgeError, parse_source_fact, resolve_feature_row
from .live_slate import LiveGame, TeamLineup, lineup_from_rows
from .mlb_source import fetch_boxscore, fetch_schedule, parse_confirmed_lineup, parse_game_start
from .quote_bridge import QuoteBridgeError, validate_canonical_quote
from .runtime import parse_timestamp
from .unified_card import UnifiedCardResult, run_unified_card

CHICAGO_TZ = ZoneInfo("America/Chicago")
GAME_MARKETS = frozenset({"MONEYLINE", "RUN_LINE", "TOTALS", "NRFI", "YRFI"})

class AutoRunnerError(RuntimeError):
    pass

@dataclass(frozen=True)
class AutoCardResult:
    source_index: int
    game_id: str
    market: str
    entity_id: str
    line: Any
    side: str
    book_key: str
    american_odds: Any
    model_p: float | None
    bet_status: str
    reason: str

@dataclass(frozen=True)
class AutoRunReport:
    slate_date_ct: str
    generated_at_utc: str
    run_status: str
    results: tuple[AutoCardResult, ...]
    source_failures: tuple[dict[str, Any], ...]

def _aware_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise AutoRunnerError("NOW_TIMEZONE_REQUIRED")
    return value.astimezone(timezone.utc)

def _http_json(url: str, *, opener: Callable = urlopen, token: str | None = None) -> Any:
    if not isinstance(url, str) or not url.strip(): raise AutoRunnerError("PROVIDER_URL_MISSING")
    headers={"Accept":"application/json"}
    if token: headers["Authorization"]=f"Bearer {token}"
    req=Request(url.strip(),headers=headers)
    try:
        with opener(req,timeout=15) as response: return json.loads(response.read().decode("utf-8"))
    except Exception as exc: raise AutoRunnerError(f"PROVIDER_FETCH_FAILED: {url}") from exc

def _snapshot_list(name: str, value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value,list): raise AutoRunnerError(f"{name}_SNAPSHOT_NOT_LIST")
    out=[]
    for item in value:
        if not isinstance(item,Mapping): raise AutoRunnerError(f"{name}_SNAPSHOT_ROW_MALFORMED")
        out.append(item)
    return out

def _canonical_quotes(raw_quotes: list[Mapping[str, Any]]) -> tuple[list[Mapping[str, Any]], dict[int,str]]:
    quotes=[]; failures={}; seen=set()
    for i,raw in enumerate(raw_quotes):
        try:
            q=validate_canonical_quote(raw)
            key=(q["game_id"],q["period"],q["market"],q["entity_id"],repr(q["line"]),q["side"],q["book_key"],q["is_alternate"],q["american_odds"])
            if key in seen: raise QuoteBridgeError("duplicate sportsbook offer")
            seen.add(key); quotes.append({"source_index":i,**q})
        except Exception as exc: failures[i]=f"{type(exc).__name__}: {exc}"
    return quotes,failures

def _projected_index(rows: list[Mapping[str, Any]]) -> dict[tuple[int,int,str],Mapping[str,Any]]:
    out={}
    for row in rows:
        try: game_pk=int(row["game_pk"]); team_id=int(row["team_id"]); side=str(row["side"])
        except Exception as exc: raise AutoRunnerError("PROJECTED_LINEUP_IDENTITY_MALFORMED") from exc
        if game_pk<=0 or team_id<=0 or side not in {"away","home"}: raise AutoRunnerError("PROJECTED_LINEUP_IDENTITY_MALFORMED")
        key=(game_pk,team_id,side)
        if key in out: raise AutoRunnerError("PROJECTED_LINEUP_DUPLICATE")
        out[key]=row
    return out

def _projected_lineup(envelope: Mapping[str,Any]|None, *, team_id:int, side:str, now:datetime) -> TeamLineup:
    if envelope is None: return TeamLineup(team_id,side,(),(),False)
    try: retrieved=parse_timestamp(envelope.get("retrieved_at"))
    except Exception as exc: raise AutoRunnerError("PROJECTED_LINEUP_TIMESTAMP_INVALID") from exc
    if retrieved>now: raise AutoRunnerError("PROJECTED_LINEUP_FUTURE_RETRIEVAL")
    ttl=envelope.get("ttl_seconds",900)
    if isinstance(ttl,bool): raise AutoRunnerError("PROJECTED_LINEUP_TTL_INVALID")
    try: ttl=float(ttl)
    except (TypeError,ValueError) as exc: raise AutoRunnerError("PROJECTED_LINEUP_TTL_INVALID") from exc
    if not isfinite(ttl) or ttl<=0: raise AutoRunnerError("PROJECTED_LINEUP_TTL_INVALID")
    if (now-retrieved).total_seconds()>ttl: raise AutoRunnerError("PROJECTED_LINEUP_STALE")
    rows=envelope.get("rows")
    if not isinstance(rows,list): raise AutoRunnerError("PROJECTED_LINEUP_ROWS_MALFORMED")
    validated=lineup_from_rows(team_id,side,rows)
    if set(validated.batting_slots)!=set(range(1,10)) or len(validated.player_ids)!=9: raise AutoRunnerError("PROJECTED_LINEUP_INCOMPLETE")
    return TeamLineup(validated.team_id,validated.side,validated.player_ids,validated.batting_slots,False)

def _live_game(snapshot, *, boxscore:Mapping[str,Any], projected:dict[tuple[int,int,str],Mapping[str,Any]], now:datetime) -> LiveGame:
    def side_lineup(side:str, team_id:int) -> TeamLineup:
        confirmed_rows=parse_confirmed_lineup(dict(boxscore),side); confirmed=lineup_from_rows(team_id,side,confirmed_rows)
        if confirmed.confirmed: return confirmed
        return _projected_lineup(projected.get((snapshot.game_pk,team_id,side)),team_id=team_id,side=side,now=now)
    return LiveGame(game_pk=snapshot.game_pk,away_team_id=snapshot.away_id,home_team_id=snapshot.home_id,away_probable_pitcher_id=snapshot.away_probable_pitcher_id,home_probable_pitcher_id=snapshot.home_probable_pitcher_id,away_lineup=side_lineup("away",snapshot.away_id),home_lineup=side_lineup("home",snapshot.home_id),game_number=snapshot.game_number,double_header=snapshot.double_header,venue_id=snapshot.venue_id,official_date=snapshot.official_date,status=snapshot.status)

def _feature_envelopes(rows:list[Mapping[str,Any]]) -> dict[tuple[int,int,str],Mapping[str,Any]]:
    out={}
    for row in rows:
        try: key=(int(row["game_pk"]),int(row["player_id"]),str(row["market"]))
        except Exception as exc: raise AutoRunnerError("FEATURE_ENVELOPE_IDENTITY_MALFORMED") from exc
        if key[0]<=0 or key[1]<=0: raise AutoRunnerError("FEATURE_ENVELOPE_IDENTITY_MALFORMED")
        if key in out: raise AutoRunnerError("FEATURE_ENVELOPE_DUPLICATE")
        out[key]=row
    return out

def _resolve_feature(envelope:Mapping[str,Any], *, now:datetime, game_start:datetime) -> dict[str,Any]:
    sources=envelope.get("sources")
    if not isinstance(sources,list): raise FeatureBridgeError("MALFORMED",{"field":"sources"})
    for raw in sources:
        fact=parse_source_fact(raw)
        if fact.event_time>fact.retrieved_at: raise FeatureBridgeError("IMPOSSIBLE_SOURCE_CHRONOLOGY",{"source_id":fact.source_id,"fact_key":fact.fact_key})
        if fact.retrieved_at>game_start: raise FeatureBridgeError("POST_CUTOFF_RETRIEVAL",{"source_id":fact.source_id,"fact_key":fact.fact_key})
    return resolve_feature_row(market=str(envelope.get("market")),game_pk=int(envelope.get("game_pk")),player_id=int(envelope.get("player_id")),team_id=int(envelope.get("team_id")),feature_fact_keys=envelope.get("feature_fact_keys") or {},sources=sources,ttl_by_feature=envelope.get("ttl_by_feature") or {},now=now,wager_cutoff=game_start)

def _blocked(index:int, raw:Mapping[str,Any]|None, reason:str) -> AutoCardResult:
    raw=raw or {}
    return AutoCardResult(index,str(raw.get("game_id","UNKNOWN")),str(raw.get("market","UNKNOWN")),str(raw.get("entity_id","UNKNOWN")),raw.get("line"),str(raw.get("side","UNKNOWN")),str(raw.get("book_key") or "MISSING"),raw.get("american_odds"),None,"BLOCKED",reason)

def _convert(index:int, result:UnifiedCardResult, *, book_key:str) -> AutoCardResult:
    book=str(book_key or "").strip()
    if not book:
        raise AutoRunnerError("BOOK_KEY_MISSING_AT_FINAL_CARD")
    return AutoCardResult(index,result.game_id,result.market,result.entity_id,result.line,result.side,book,result.american_odds,result.model_p,result.bet_status,result.reason)

def run_auto_mlb(*, quote_url:str, feature_url:str, projected_lineups_url:str|None=None, projected_lineup_rows:list[Mapping[str,Any]]|None=None, provider_token:str|None=None, now:datetime|None=None, opener:Callable=urlopen, registry_path:str="config/deployments.json", require_confirmed_lineup:bool=False, min_edge:float=0.0, kelly_multiplier:float=0.25, game_feature_rows:list[Mapping[str,Any]]|None=None, game_score_artifact:Mapping[str,Any]|None=None, nrfi_artifact:Mapping[str,Any]|None=None) -> AutoRunReport:
    current=_aware_utc(now or datetime.now(timezone.utc)); slate_date_ct=current.astimezone(CHICAGO_TZ).date().isoformat()
    raw_quote_rows=_snapshot_list("QUOTE",_http_json(quote_url,opener=opener,token=provider_token))
    feature_rows_raw=_snapshot_list("FEATURE",_http_json(feature_url,opener=opener,token=provider_token))
    if projected_lineups_url and projected_lineup_rows is not None: raise AutoRunnerError("PROJECTED_LINEUP_SOURCE_AMBIGUOUS")
    if projected_lineups_url:
        projected_raw=_snapshot_list("PROJECTED_LINEUP",_http_json(projected_lineups_url,opener=opener,token=provider_token))
    elif projected_lineup_rows is not None:
        projected_raw=_snapshot_list("PROJECTED_LINEUP",projected_lineup_rows)
    else:
        projected_raw=[]
    canonical_quotes,quote_failures=_canonical_quotes(raw_quote_rows); projected=_projected_index(projected_raw); envelopes=_feature_envelopes(feature_rows_raw)
    schedule=fetch_schedule(slate_date_ct,opener=opener,now=current); snapshots={str(g.game_pk):g for g in schedule}; games=[]; game_failures={}
    for snap in schedule:
        game_id=str(snap.game_pk)
        try:
            start=parse_game_start(snap.game_date)
            if snap.status!="Preview": raise AutoRunnerError("GAME_NOT_PREGAME")
            if current>=start: raise AutoRunnerError("GAME_CLOCK_NOT_PREGAME")
            boxscore=fetch_boxscore(snap.game_pk,opener=opener); games.append(_live_game(snap,boxscore=boxscore,projected=projected,now=current))
        except Exception as exc: game_failures[game_id]=f"{type(exc).__name__}: {exc}"
    resolved_features=[]; feature_failures={}
    for q in canonical_quotes:
        game_id,entity_id,market=q["game_id"],q["entity_id"],q["market"]; identity=(game_id,entity_id,market)
        if game_id in game_failures: continue
        snap=snapshots.get(game_id)
        if snap is None: continue
        if market in GAME_MARKETS: continue
        try:
            env=envelopes.get((int(game_id),int(entity_id),market))
            if env is None: raise FeatureBridgeError("MISSING",{"detail":"feature envelope missing"})
            resolved_features.append(_resolve_feature(env,now=current,game_start=parse_game_start(snap.game_date)))
        except Exception as exc: feature_failures[identity]=f"{type(exc).__name__}: {exc}"
    q_for_runner=[{k:v for k,v in q.items() if k!="source_index"} for q in canonical_quotes]
    unified=run_unified_card(games=games,feature_rows=resolved_features,quotes=q_for_runner,ingestion_now=current,finalization_now=current,registry_path=registry_path,require_confirmed_lineup=require_confirmed_lineup,min_edge=min_edge,kelly_multiplier=kelly_multiplier,game_feature_rows=game_feature_rows,game_score_artifact=game_score_artifact,nrfi_artifact=nrfi_artifact)
    output={}
    for i,reason in quote_failures.items(): output[i]=_blocked(i,raw_quote_rows[i],reason)
    for q,result in zip(canonical_quotes,unified):
        i=int(q["source_index"]); identity=(q["game_id"],q["entity_id"],q["market"])
        if q["game_id"] in game_failures: output[i]=_blocked(i,q,game_failures[q["game_id"]])
        elif snapshots.get(q["game_id"]) is None: output[i]=_blocked(i,q,"MLB_GAME_ID_NOT_FOUND")
        elif q["market"] not in GAME_MARKETS and identity in feature_failures: output[i]=_blocked(i,q,feature_failures[identity])
        else: output[i]=_convert(i,result,book_key=q["book_key"])
    results=tuple(output[i] for i in range(len(raw_quote_rows))); source_failures=tuple({"source_index":r.source_index,"reason":r.reason} for r in results if r.bet_status=="BLOCKED")
    status="PASS" if results else "NO_QUOTES"
    return AutoRunReport(slate_date_ct,current.isoformat(),status,results,source_failures)

def report_to_dict(report:AutoRunReport) -> dict[str,Any]:
    return {"slate_date_ct":report.slate_date_ct,"generated_at_utc":report.generated_at_utc,"run_status":report.run_status,"results":[asdict(x) for x in report.results],"source_failures":list(report.source_failures)}
