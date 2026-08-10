#!/usr/bin/env python3
"""Adapters constrained to the documented MLB shapes captured in the compatibility audit.

This module does NOT claim live-payload parity. It only maps fields that the audit
marked CONFIRMED and fails closed on undocumented native concepts such as bullpen
availability and opener/bulk role.
"""
from __future__ import annotations
from typing import Any, Dict, List
from mlb_source_adapters_v0_2 import (
    AdapterError, BridgeSourceRecord, AUTHORITY_RANK, DEFAULT_TTL_SECONDS, _common, _ts, _pid, _side
)

SCHEMA_VERSION = "0.3-doc"


def _gamepk(v: Any) -> int:
    if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
        raise AdapterError(f"gamePk missing/invalid: {v!r}")
    return v


def adapt_schedule_identity(raw: Dict[str, Any], provider: str, authority: str, fetched_at: str) -> BridgeSourceRecord:
    """Map documented schedule gamePk to canonical SportsEdge game identity."""
    _common(provider, authority, fetched_at)
    if "gamePk" not in raw:
        raise AdapterError("schedule game missing gamePk")
    gp = _gamepk(raw["gamePk"])
    return BridgeSourceRecord(
        source_id=f"{provider}_gamePk_{gp}_{fetched_at}",
        fact_key=f"game_identity:{gp}",
        value=gp,
        provider=provider,
        authority=authority,
        event_time=fetched_at,
        retrieved_at=fetched_at,
        ttl_seconds=86400,
        game_id=str(gp),
        entity_id=None,
        status=None,
        schema_version=SCHEMA_VERSION,
    )


def adapt_documented_probable_pitcher(raw: Dict[str, Any], side: str, provider: str, authority: str, fetched_at: str) -> BridgeSourceRecord:
    """Map gameData.probablePitchers.{home,away}.id.

    MLB documentation captured in the audit does not expose a native confirmed flag
    or opener/bulk role. Therefore this adapter emits PROJECTED starter identity only.
    """
    _common(provider, authority, fetched_at)
    side = _side(side)
    gp = _gamepk(raw.get("gamePk"))
    gd = raw.get("gameData")
    if not isinstance(gd, dict):
        raise AdapterError("gameData missing/invalid")
    pp = gd.get("probablePitchers")
    if not isinstance(pp, dict):
        raise AdapterError("probablePitchers missing/invalid")
    person = pp.get(side)
    if not isinstance(person, dict) or "id" not in person:
        raise AdapterError(f"probablePitchers.{side}.id missing")
    pid = _pid(person["id"])
    return BridgeSourceRecord(
        source_id=f"{provider}_{gp}_{side}_probable_{pid}_{fetched_at}",
        fact_key=f"starter:{gp}:{side}",
        value=pid,
        provider=provider,
        authority=authority,
        event_time=fetched_at,
        retrieved_at=fetched_at,
        ttl_seconds=DEFAULT_TTL_SECONDS["starter"],
        game_id=str(gp),
        entity_id=pid,
        status="PROJECTED",
        schema_version=SCHEMA_VERSION,
    )


def adapt_documented_batting_order(raw: Dict[str, Any], side: str, provider: str, authority: str,
                                     fetched_at: str, *, snapshot_time: str, pregame_attested: bool) -> List[BridgeSourceRecord]:
    """Map TeamBoxscore.battingOrder:number[] to slots 1..9.

    A current/final boxscore is not inherently pregame-safe. Caller must supply an
    explicit snapshot_time and pregame_attested=True (for example from a verified
    timecoded snapshot before first pitch) or this adapter refuses to emit lineup facts.
    """
    _common(provider, authority, fetched_at)
    side = _side(side)
    gp = _gamepk(raw.get("gamePk"))
    _ts(snapshot_time, "snapshot_time")
    if pregame_attested is not True:
        raise AdapterError("battingOrder snapshot is not attested pregame")
    live = raw.get("liveData")
    box = live.get("boxscore") if isinstance(live, dict) else None
    teams = box.get("teams") if isinstance(box, dict) else None
    team = teams.get(side) if isinstance(teams, dict) else None
    order = team.get("battingOrder") if isinstance(team, dict) else None
    if not isinstance(order, list) or len(order) != 9:
        raise AdapterError("documented battingOrder must be a 9-player list")
    seen = set(); out=[]
    for i, raw_pid in enumerate(order, 1):
        pid = _pid(raw_pid)
        if pid in seen:
            raise AdapterError(f"duplicate battingOrder player {pid}")
        seen.add(pid)
        out.append(BridgeSourceRecord(
            source_id=f"{provider}_{gp}_{side}_slot{i}_{snapshot_time}",
            fact_key=f"lineup_slot:{gp}:{side}:{i}",
            value=pid,
            provider=provider,
            authority=authority,
            event_time=snapshot_time,
            retrieved_at=fetched_at,
            ttl_seconds=DEFAULT_TTL_SECONDS["lineup_slot"],
            game_id=str(gp),
            entity_id=pid,
            status="CONFIRMED",
            schema_version=SCHEMA_VERSION,
        ))
    return out


def adapt_documented_game_status(raw: Dict[str, Any], provider: str, authority: str, fetched_at: str) -> BridgeSourceRecord:
    _common(provider, authority, fetched_at)
    gp = _gamepk(raw.get("gamePk"))
    gd = raw.get("gameData")
    status = gd.get("status") if isinstance(gd, dict) else None
    abstract = status.get("abstractGameState") if isinstance(status, dict) else None
    if abstract not in {"Preview", "Live", "Final"}:
        raise AdapterError(f"undocumented/unknown abstractGameState {abstract!r}")
    return BridgeSourceRecord(
        source_id=f"{provider}_{gp}_status_{fetched_at}", fact_key=f"game_state:{gp}", value=abstract,
        provider=provider, authority=authority, event_time=fetched_at, retrieved_at=fetched_at,
        ttl_seconds=300, game_id=str(gp), schema_version=SCHEMA_VERSION
    )


def adapt_documented_roof_type(raw: Dict[str, Any], provider: str, authority: str, fetched_at: str) -> BridgeSourceRecord:
    """Map static roof TYPE only; does not claim retractable roof open/closed state."""
    _common(provider, authority, fetched_at)
    gp = _gamepk(raw.get("gamePk"))
    gd = raw.get("gameData")
    venue = gd.get("venue") if isinstance(gd, dict) else None
    fi = venue.get("fieldInfo") if isinstance(venue, dict) else None
    roof = fi.get("roofType") if isinstance(fi, dict) else None
    if roof not in {"Open", "Retractable", "Dome"}:
        raise AdapterError(f"roofType missing/invalid: {roof!r}")
    return BridgeSourceRecord(
        source_id=f"{provider}_{gp}_roof_type_{fetched_at}", fact_key=f"roof_type:{gp}", value=roof,
        provider=provider, authority=authority, event_time=fetched_at, retrieved_at=fetched_at,
        ttl_seconds=86400, game_id=str(gp), schema_version=SCHEMA_VERSION
    )


def adapt_native_bullpen_availability(*args, **kwargs):
    raise AdapterError("MLB documented schema does not expose native bullpen availability; derive from prior appearances")


def adapt_native_starter_role(*args, **kwargs):
    raise AdapterError("MLB documented schema does not expose opener/bulk/traditional starter role")
