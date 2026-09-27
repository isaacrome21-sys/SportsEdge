"""DRAFTKINGS_DIRECT_WEB_V1 acquisition adapter for NFL confirmation capture.

Transport/admission only; grants no Model_P, promotion, Truth Gate, staking, or
OFFICIAL authority.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from sportsedge.draftkings_game_market_source import (
    DraftKingsGameMarketError, board_url, fetch_board, normalize_board,
)

SOURCE_CLASS = "DRAFTKINGS_DIRECT_WEB_V1"
PROVIDER = "DRAFTKINGS_DIRECT_WEB"
SPORTSBOOK = "draftkings"

class DirectCaptureError(RuntimeError): pass

def adapter_module_sha256() -> str: return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
def _now() -> datetime: return datetime.now(timezone.utc)
def _iso_z(dt: datetime) -> str:
    if dt.tzinfo is None or dt.utcoffset() is None: raise DirectCaptureError("DK_DIRECT_TIME_NAIVE")
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
def _host_of(uri: str) -> str: return str(uri).split("//",1)[-1].split("/",1)[0]

def acquire_board(sport_key="americanfootball_nfl", *, fetcher: Callable[...,Any]=fetch_board, clock: Callable[[],datetime]=_now):
    uri=board_url(sport_key); started=clock(); attempts=[]
    try: board=fetcher(sport_key)
    except DraftKingsGameMarketError as exc:
        attempts.append({"attempt":1,"host":_host_of(uri),"result_class":str(exc),"received_at_utc":_iso_z(clock())})
        err=DirectCaptureError("DK_DIRECT_BOARD_UNAVAILABLE"); err.attempts=attempts; raise err from exc
    received=board.received_at
    attempts.append({"attempt":1,"host":_host_of(board.source_uri),"result_class":"OK","received_at_utc":_iso_z(received)})
    return {"source_class":SOURCE_CLASS,"provider":PROVIDER,"sportsbook":SPORTSBOOK,"sport_key":board.sport_key,"source_uri":board.source_uri,"transport_host":_host_of(board.source_uri),"requested_at_utc":_iso_z(started),"observed_at_utc":_iso_z(received),"raw_bytes":board.raw,"raw_sha256":hashlib.sha256(board.raw).hexdigest(),"raw_payload":board.payload,"attempts":attempts,"adapter_module_sha256":adapter_module_sha256(),"book_last_update":None,"provider_quote_timestamp_available":False}

def _pair(rows: Sequence[Mapping[str,Any]], market: str): return [r for r in rows if r.get("market")==market]
def _event_teams(event):
    name=str(event.get("name") or "").strip()
    if " @ " not in name: raise DirectCaptureError("DK_DIRECT_EVENT_TEAMS_INVALID")
    away,home=(x.strip() for x in name.split(" @ ",1))
    if not away or not home: raise DirectCaptureError("DK_DIRECT_EVENT_TEAMS_INVALID")
    return away,home
def _parse_start(value):
    try: dt=datetime.fromisoformat(str(value or "").strip().replace("Z","+00:00"))
    except Exception as exc: raise DirectCaptureError("DK_DIRECT_EVENT_START_INVALID") from exc
    if dt.tzinfo is None or dt.utcoffset() is None: raise DirectCaptureError("DK_DIRECT_EVENT_START_INVALID")
    return dt.astimezone(timezone.utc)
def _raw_market_presence(payload,event_id,names):
    ids={str(m.get("id")) for m in payload.get("markets",[]) if isinstance(m,Mapping) and str(m.get("eventId") or "")==event_id and str(m.get("name") or "").strip() in names and m.get("id") is not None}
    if not ids:return False,0
    return True,sum(1 for s in payload.get("selections",[]) if isinstance(s,Mapping) and str(s.get("marketId") or "") in ids)

def game_rows_direct(transport, *, week_of, window_start=None, window_end=None):
    from sportsedge.draftkings_game_market_source import RawDraftKingsBoard
    payload=transport.get("raw_payload")
    if not isinstance(payload,Mapping): raise DirectCaptureError("DK_DIRECT_PAYLOAD_INVALID")
    board=RawDraftKingsBoard(str(transport.get("sport_key") or "americanfootball_nfl"),str(transport["source_uri"]),bytes(transport.get("raw_bytes") or b""),datetime.fromisoformat(str(transport["observed_at_utc"]).replace("Z","+00:00")),payload)
    normalized=normalize_board(board); by_event={}
    for q in normalized: by_event.setdefault(str(q["provider_event_id"]),[]).append(q)
    out=[]; failures=0
    for event in payload.get("events",[]):
        if not isinstance(event,Mapping) or event.get("id") is None: continue
        eid=str(event["id"])
        try: commence=_parse_start(event.get("startEventDate")); away,home=_event_teams(event)
        except DirectCaptureError: failures+=1; continue
        if window_start is not None and commence < window_start: continue
        if window_end is not None and commence >= window_end: continue
        rows=by_event.get(eid,[]); row={"event_id":eid,"home_team":home,"away_team":away,"commence_time":_iso_z(commence),"week":week_of(commence),"book":SPORTSBOOK,"source_class":SOURCE_CLASS,"book_last_update":None,"observed_at_utc":transport["observed_at_utc"]}
        spreads=_pair(rows,"spreads"); exists,n=_raw_market_presence(payload,eid,{"Spread","Run Line"})
        if len(spreads)==2:
            h=next((s for s in spreads if s.get("outcome")==home),None); a=next((s for s in spreads if s.get("outcome")==away),None)
            if h is None or a is None or h.get("point") is None or a.get("point") is None: row["spread"]={"status":"ONE_SIDED"}
            elif float(h["point"]) != -float(a["point"]): row["spread"]={"status":"LINE_MISMATCH"}
            else: row["spread"]={"status":"OK","market_last_update":None,"home_point":h["point"],"home_price":h["price_american"],"away_point":a["point"],"away_price":a["price_american"]}
        else: row["spread"]={"status":"NOT_LISTED" if not exists else "ONE_SIDED" if n<2 else "UNADMITTED_MARKET"}
        totals=_pair(rows,"totals"); exists,n=_raw_market_presence(payload,eid,{"Total"})
        if len(totals)==2:
            over=next((t for t in totals if t.get("outcome")=="Over"),None); under=next((t for t in totals if t.get("outcome")=="Under"),None)
            if over is None or under is None: row["total"]={"status":"ONE_SIDED"}
            elif over.get("point") is None or over.get("point") != under.get("point"): row["total"]={"status":"LINE_MISMATCH"}
            else: row["total"]={"status":"OK","market_last_update":None,"point":over["point"],"over_price":over["price_american"],"under_price":under["price_american"]}
        else: row["total"]={"status":"NOT_LISTED" if not exists else "ONE_SIDED" if n<2 else "UNADMITTED_MARKET"}
        out.append(row)
    if failures: raise DirectCaptureError("DK_DIRECT_EVENT_IDENTITY_UNADMITTED")
    return out
