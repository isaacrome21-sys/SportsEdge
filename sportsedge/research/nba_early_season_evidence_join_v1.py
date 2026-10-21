"""Explicit two-source NBA player boxscore chronology join, research-only.

The SportsDataverse NBA Results Pull has no event time/availability or player
position. This join requires separately recorded event *result receipt* and
roster identity evidence, keyed by exact event and player/team IDs. A
successful structural join does NOT independently authenticate the receipts
or authorize the frozen prop construction or a bet. Never infer a receipt
from file download time, game ID or historical final score.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from zoneinfo import ZoneInfo


ENGINE="NBA_EARLY_SEASON_INPUT_EVIDENCE_JOIN_V1"
_CST=ZoneInfo("America/Chicago")


def _ts(x, what):
    try:
        t=x if isinstance(x,datetime) else datetime.fromisoformat(str(x).replace("Z","+00:00"))
    except (ValueError,TypeError) as e:
        raise ValueError(what+"_TIMESTAMP_INVALID") from e
    if t.tzinfo is None or t.utcoffset() is None:
        raise ValueError(what+"_TIMEZONE_REQUIRED")
    return t.astimezone(timezone.utc)


def _named(v,what):
    s=str(v if v is not None else "").strip()
    if not s:
        raise ValueError(what+"_MISSING")
    return s


def _count(v,what):
    if isinstance(v,bool):
        raise ValueError(what+"_INVALID")
    try: n=float(v)
    except (ValueError,TypeError) as e: raise ValueError(what+"_INVALID") from e
    if not isfinite(n) or n<0:
        raise ValueError(what+"_INVALID")
    return n


def _minutes(v):
    if isinstance(v,str) and ":" in v:
        parts=v.split(":")
        if len(parts)!=2 or not parts[0].isdigit() or not parts[1].isdigit() or int(parts[1])>=60:
            raise ValueError("NBA_EARLY_JOIN_MINUTES_INVALID")
        return float(int(parts[0]))+int(parts[1])/60
    return _count(v,"NBA_EARLY_JOIN_MINUTES")


def _season(v):
    label=_named(v,"NBA_EARLY_JOIN_SEASON")
    if len(label)!=7 or label[4]!="-" or not label[:4].isdigit() or not label[5:].isdigit():
        raise ValueError("NBA_EARLY_JOIN_SEASON_LABEL_UNVERIFIED")
    start=int(label[:4])
    if int(label[5:])!=(start+1)%100:
        raise ValueError("NBA_EARLY_JOIN_SEASON_LABEL_UNVERIFIED")
    return start


def join_nba_boxscore_evidence(boxes, event_receipts, player_roles):
    """Return canonical V2 research rows and explicit non-admission state.

    boxes: genuine Results Pull rows PLAYER_ID/GAME_ID/TEAM_ABBREVIATION/
           SEASON ('2025-26')/SEASON_TYPE_ID ('2')/MIN/PTS/REB/AST.
    event_receipts: rows event_id, tipoff, finalized_at, result_observed_at,\n        event_state=FINAL, result_state=FINAL, source_ref.
        result_observed_at MUST be a preserved receipt, not a reconstructed
        historical timestamp.
    player_roles: rows player_id, team_abbreviation, position,
        observed_at (pre-event receipt), source_ref.
    Duplicate or missing matching evidence aborts the whole join.
    """
    es={}
    for src in event_receipts:
        gid=_named(src.get("event_id"),"NBA_EARLY_JOIN_EVENT_ID")
        if gid in es:
            raise ValueError("NBA_EARLY_JOIN_DUPLICATE_EVENT_RECEIPT")
        tip=_ts(src.get("tipoff"),"NBA_EARLY_JOIN_TIPOFF")
        observed=_ts(src.get("result_observed_at"),"NBA_EARLY_JOIN_FINAL_RECEIPT")
        if observed<=tip:
            raise ValueError("NBA_EARLY_JOIN_FINAL_RECEIPT_NOT_AFTER_TIP")
        # A timestamp after tipoff alone does not prove final-result availability.
        # Caller-supplied final-state evidence remains unauthenticated.
        if src.get("event_state") != "FINAL" or src.get("result_state") != "FINAL":
            raise ValueError("NBA_EARLY_JOIN_FINAL_STATE_WITNESS_MISSING")
        finalized=_ts(src.get("finalized_at"),"NBA_EARLY_JOIN_FINALIZED_AT")
        if finalized<=tip or observed<finalized:
            raise ValueError("NBA_EARLY_JOIN_FINAL_STATE_CHRONOLOGY_INVALID")
        es[gid]=(tip,observed,_named(src.get("source_ref"),"NBA_EARLY_JOIN_EVENT_SOURCE"))
    roles={}
    for src in player_roles:
        pid=_named(src.get("player_id"),"NBA_EARLY_JOIN_ROLE_PLAYER")
        team=_named(src.get("team_abbreviation"),"NBA_EARLY_JOIN_ROLE_TEAM")
        observed=_ts(src.get("observed_at"),"NBA_EARLY_JOIN_ROLE_OBSERVED")
        position=_named(src.get("position"),"NBA_EARLY_JOIN_ROLE_POSITION")
        ref=_named(src.get("source_ref"),"NBA_EARLY_JOIN_ROLE_SOURCE")
        key=(pid,team)
        roles.setdefault(key,[]).append((observed,position,ref))
    result=[]
    ids=set()
    skipped_non_regular=0
    for box in boxes:
        # Drop playoffs and preseason only when a real source type was
        # supplied. A missing season_type_id is not assumed 'regular'.
        typ=_named(box.get("SEASON_TYPE_ID"),"NBA_EARLY_JOIN_SEASON_TYPE")
        if typ not in {"2","Regular Season"}:
            skipped_non_regular+=1
            continue
        pid=_named(box.get("PLAYER_ID"),"NBA_EARLY_JOIN_PLAYER_ID")
        gid=_named(box.get("GAME_ID"),"NBA_EARLY_JOIN_GAME_ID")
        team=_named(box.get("TEAM_ABBREVIATION"),"NBA_EARLY_JOIN_TEAM")
        season=_season(box.get("SEASON"))
        key=(pid,gid)
        if key in ids:
            raise ValueError("NBA_EARLY_JOIN_DUPLICATE_PLAYER_GAME")
        ids.add(key)
        if gid not in es:
            raise ValueError("NBA_EARLY_JOIN_EVENT_RECEIPT_MISSING:"+gid)
        tip,final_receipt,src=es[gid]
        # NBA season labels identify the league season *starting* this year;
        # game dates can cross into the following calendar year.
        if not ((tip.year==season and tip.month>=10) or
                (tip.year==season+1 and tip.month<=6)):
            raise ValueError("NBA_EARLY_JOIN_SEASON_TIPOFF_INCONSISTENT")
        eligible=sorted((z for z in roles.get((pid,team),[]) if z[0]<tip),key=lambda z:z[0])
        if not eligible:
            raise ValueError("NBA_EARLY_JOIN_PREGAME_ROLE_RECEIPT_MISSING")
        if len({z[1] for z in eligible})>1:
            raise ValueError("NBA_EARLY_JOIN_CONFLICTING_PLAYER_ROLE")
        role_receipt,position,role_ref=eligible[-1]
        minutes=_minutes(box.get("MIN"))
        pts=_count(box.get("PTS"),"NBA_EARLY_JOIN_PTS")
        reb=_count(box.get("REB"),"NBA_EARLY_JOIN_REB")
        ast=_count(box.get("AST"),"NBA_EARLY_JOIN_AST")
        result.append({
            "player_id":pid,"game_id":gid,"season":season,
            "game_date":tip.astimezone(_CST).date().isoformat(),
            "tipoff":tip.isoformat(),"observed_at":final_receipt.isoformat(),
            "source_ref":src+"|role:"+role_ref,
            "team_id":team,"position":position,"minutes":minutes,
            "points":pts,"rebounds":reb,"assists":ast,
        })
    return {"engine_id":ENGINE,"status":"STRUCTURALLY_JOINED_UNAUTHENTICATED",
            "rows":result,"joined":len(result),"skipped_non_regular":skipped_non_regular,
            "receipt_authentication":"NOT_ESTABLISHED_BY_CALLER_FIELDS",
            "market_validation":"NONE","research_only":True,"play_authority":False}
