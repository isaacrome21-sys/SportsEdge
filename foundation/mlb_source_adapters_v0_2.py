#!/usr/bin/env python3
"""Fail-closed MLB source adapters for SportsEdge live ingestion."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

SCHEMA_VERSION="0.2"
AUTHORITY_RANK={"MLB_OFFICIAL":100,"TEAM_OFFICIAL":90,"BEAT_REPORTER_VERIFIED":60,"AGGREGATOR":30,"SOCIAL_UNVERIFIED":0}
DEFAULT_TTL_SECONDS={"price":300,"starter":10800,"starter_role":10800,"lineup_slot":5400,"scratch":1800,"bullpen_availability":5400}

@dataclass(frozen=True)
class BridgeSourceRecord:
    source_id:str; fact_key:str; value:Any; provider:str; authority:str
    event_time:str; retrieved_at:str; ttl_seconds:int; game_id:str
    entity_id:Optional[str]=None; status:Optional[str]=None; schema_version:str=SCHEMA_VERSION
    @property
    def authority_rank(self)->int: return AUTHORITY_RANK[self.authority]

class AdapterError(Exception): pass

def _ts(s, field):
    if not isinstance(s,str) or not s.strip(): raise AdapterError(f"{field} missing/invalid")
    try: d=datetime.fromisoformat(s.replace("Z","+00:00"))
    except Exception as e: raise AdapterError(f"{field} invalid timestamp: {e}")
    if d.tzinfo is None: raise AdapterError(f"{field} missing timezone")
    return d.astimezone(timezone.utc)

def _common(provider,authority,fetched_at):
    if not isinstance(provider,str) or not provider.strip(): raise AdapterError("provider missing/invalid")
    if authority not in AUTHORITY_RANK: raise AdapterError(f"unknown authority {authority!r}")
    _ts(fetched_at,"fetched_at")

def _gid(v):
    if not isinstance(v,str) or not v.strip(): raise AdapterError("game_id missing/invalid")
    return v.strip()

def _pid(v):
    if not isinstance(v,(str,int)) or isinstance(v,bool) or str(v).strip()=="":
        raise AdapterError("player_id missing/invalid")
    return str(v)

def _side(v):
    if v not in ("home","away"): raise AdapterError(f"invalid side {v!r}")
    return v

def adapt_probable_starter(raw,provider,authority,fetched_at):
    _common(provider,authority,fetched_at)
    for k in ("game_id","side","player_id","role","announced_at"):
        if k not in raw: raise AdapterError(f"probable-starter missing {k}")
    gid=_gid(raw["game_id"]); side=_side(raw["side"]); pid=_pid(raw["player_id"])
    role=raw["role"]
    if role not in ("starter","opener","bulk"): raise AdapterError(f"invalid role {role!r}")
    _ts(raw["announced_at"],"announced_at")
    confirmed=raw.get("confirmed",False)
    if not isinstance(confirmed,bool): raise AdapterError("confirmed must be bool")
    status="CONFIRMED" if confirmed else "PROJECTED"
    b=f"{provider}_{gid}_{side}_{pid}_{raw['announced_at']}"
    return [
      BridgeSourceRecord(f"{b}_starter",f"starter:{gid}:{side}",pid,provider,authority,raw["announced_at"],fetched_at,DEFAULT_TTL_SECONDS["starter"],gid,pid,status),
      BridgeSourceRecord(f"{b}_role",f"starter_role:{gid}:{side}",role,provider,authority,raw["announced_at"],fetched_at,DEFAULT_TTL_SECONDS["starter_role"],gid,pid,status)
    ]

def adapt_lineup_card(raw,provider,authority,fetched_at):
    _common(provider,authority,fetched_at)
    for k in ("game_id","side","confirmed","posted_at","slots"):
        if k not in raw: raise AdapterError(f"lineup-card missing {k}")
    gid=_gid(raw["game_id"]); side=_side(raw["side"]); _ts(raw["posted_at"],"posted_at")
    if not isinstance(raw["confirmed"],bool): raise AdapterError("confirmed must be bool")
    slots=raw["slots"]
    if not isinstance(slots,list) or not (1<=len(slots)<=9): raise AdapterError("lineup slots must be list length 1..9")
    status="CONFIRMED" if raw["confirmed"] else "PROJECTED"; out=[]; seen=set(); players=set()
    for e in slots:
        if not isinstance(e,dict) or "slot" not in e or "player_id" not in e: raise AdapterError("malformed lineup entry")
        slot=e["slot"]; pid=_pid(e["player_id"])
        if not isinstance(slot,int) or isinstance(slot,bool) or not 1<=slot<=9: raise AdapterError(f"invalid batting slot {slot!r}")
        if slot in seen: raise AdapterError(f"duplicate slot {slot}")
        if pid in players: raise AdapterError(f"duplicate player_id {pid}")
        seen.add(slot); players.add(pid)
        out.append(BridgeSourceRecord(f"{provider}_{gid}_{side}_{slot}_{raw['posted_at']}",f"lineup_slot:{gid}:{side}:{slot}",pid,provider,authority,raw["posted_at"],fetched_at,DEFAULT_TTL_SECONDS["lineup_slot"],gid,pid,status))
    return out

def adapt_scratch(raw,provider,authority,fetched_at):
    _common(provider,authority,fetched_at)
    for k in ("game_id","side","slot","player_id","reported_at"):
        if k not in raw: raise AdapterError(f"scratch missing {k}")
    gid=_gid(raw["game_id"]); side=_side(raw["side"]); pid=_pid(raw["player_id"]); slot=raw["slot"]
    if not isinstance(slot,int) or isinstance(slot,bool) or not 1<=slot<=9: raise AdapterError(f"invalid scratch slot {slot!r}")
    _ts(raw["reported_at"],"reported_at")
    return BridgeSourceRecord(f"{provider}_{gid}_{side}_{slot}_scratch_{raw['reported_at']}",f"lineup_slot:{gid}:{side}:{slot}",None,provider,authority,raw["reported_at"],fetched_at,DEFAULT_TTL_SECONDS["scratch"],gid,pid,"SCRATCHED")

def adapt_bullpen_availability(raw,provider,authority,fetched_at):
    _common(provider,authority,fetched_at)
    for k in ("game_id","side","as_of","relievers"):
        if k not in raw: raise AdapterError(f"bullpen missing {k}")
    gid=_gid(raw["game_id"]); side=_side(raw["side"]); _ts(raw["as_of"],"as_of")
    if not isinstance(raw["relievers"],list): raise AdapterError("relievers must be list")
    out=[]; seen=set()
    for r in raw["relievers"]:
        if not isinstance(r,dict) or "player_id" not in r or "available" not in r: raise AdapterError("malformed bullpen entry")
        pid=_pid(r["player_id"])
        if pid in seen: raise AdapterError(f"duplicate reliever {pid}")
        seen.add(pid)
        if type(r["available"]) is not bool: raise AdapterError("available must be bool")
        out.append(BridgeSourceRecord(f"{provider}_{gid}_{side}_{pid}_{raw['as_of']}",f"bullpen_availability:{gid}:{side}:{pid}",r["available"],provider,authority,raw["as_of"],fetched_at,DEFAULT_TTL_SECONDS["bullpen_availability"],gid,pid))
    return out

def adapt_price(raw,provider,authority,fetched_at):
    _common(provider,authority,fetched_at)
    for k in ("game_id","market","selection","american_odds","captured_at"):
        if k not in raw: raise AdapterError(f"price missing {k}")
    gid=_gid(raw["game_id"]); _ts(raw["captured_at"],"captured_at")
    market=raw["market"]; sel=raw["selection"]; odds=raw["american_odds"]
    if not isinstance(market,str) or not market.strip(): raise AdapterError("market missing/invalid")
    if not isinstance(sel,str) or not sel.strip(): raise AdapterError("selection missing/invalid")
    if not isinstance(odds,int) or isinstance(odds,bool) or (-100 < odds < 100): raise AdapterError("american_odds must be integer <=-100 or >=100")
    return BridgeSourceRecord(f"{provider}_{gid}_{market}_{sel}_{raw['captured_at']}",f"price:{gid}:{market}:{sel}",odds,provider,authority,raw["captured_at"],fetched_at,DEFAULT_TTL_SECONDS["price"],gid)
