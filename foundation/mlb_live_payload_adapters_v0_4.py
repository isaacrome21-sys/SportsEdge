#!/usr/bin/env python3
"""MLB adapters updated from an actually observed boxscore payload.

Key observed behavior:
- team.battingOrder is an ordered 9-player array representing the current/end-state occupant of each slot;
- each player record may carry battingOrder as a string such as '300' or '301';
- integer division by 100 gives slot 1..9; remainder gives substitution sequence;
- sequence 0 is the original lineup occupant, sequence >=1 is an in-game substitute.

For LIVE authorization, lineup facts still require an explicitly attested pregame snapshot.
Final/current boxscores may be used for audit/reconstruction, never silently as pregame state.
"""
from __future__ import annotations
from typing import Any, Dict, List, Tuple
from mlb_source_adapters_v0_2 import (
    AdapterError, BridgeSourceRecord, DEFAULT_TTL_SECONDS, _common, _ts, _pid, _side
)

SCHEMA_VERSION = "0.4-livepayload"


def _gamepk(v: Any) -> int:
    if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
        raise AdapterError(f"gamePk missing/invalid: {v!r}")
    return v


def _team_boxscore(raw: Dict[str, Any], side: str) -> Tuple[int, Dict[str, Any]]:
    side = _side(side)
    gp = _gamepk(raw.get("gamePk"))
    live = raw.get("liveData")
    box = live.get("boxscore") if isinstance(live, dict) else None
    teams = box.get("teams") if isinstance(box, dict) else None
    team = teams.get(side) if isinstance(teams, dict) else None
    if not isinstance(team, dict):
        raise AdapterError(f"liveData.boxscore.teams.{side} missing/invalid")
    return gp, team


def _parse_batting_order_code(v: Any) -> Tuple[int, int]:
    if not isinstance(v, str) or not v.isdigit() or len(v) != 3:
        raise AdapterError(f"battingOrder code missing/invalid: {v!r}")
    n = int(v)
    slot, sequence = divmod(n, 100)
    if not 1 <= slot <= 9:
        raise AdapterError(f"battingOrder slot out of range: {v!r}")
    if not 0 <= sequence <= 99:
        raise AdapterError(f"battingOrder substitution sequence invalid: {v!r}")
    return slot, sequence


def extract_initial_lineup_for_audit(raw: Dict[str, Any], side: str) -> Dict[int, str]:
    """Reconstruct original 1..9 hitters from per-player battingOrder strings.

    This is an AUDIT helper. It may be used on final boxscores to identify the original
    lineup occupant (sequence 00) even when team.battingOrder has been replaced by a
    substitute. It does not attest that the lineup was known pregame.
    """
    _, team = _team_boxscore(raw, side)
    players = team.get("players")
    if not isinstance(players, dict):
        raise AdapterError("team players missing/invalid")
    starters: Dict[int, str] = {}
    for rec in players.values():
        if not isinstance(rec, dict) or "battingOrder" not in rec:
            continue
        bo = rec.get("battingOrder")
        if bo in (None, ""):
            continue
        slot, sequence = _parse_batting_order_code(bo)
        if sequence != 0:
            continue
        person = rec.get("person")
        if not isinstance(person, dict) or "id" not in person:
            raise AdapterError(f"starter battingOrder {bo} missing person.id")
        pid = _pid(person["id"])
        if slot in starters:
            raise AdapterError(f"duplicate original occupant for slot {slot}")
        starters[slot] = pid
    if set(starters) != set(range(1, 10)):
        raise AdapterError(f"original lineup incomplete; slots={sorted(starters)}")
    return starters


def extract_substitution_chain_for_audit(raw: Dict[str, Any], side: str) -> Dict[int, List[Tuple[int, str]]]:
    """Return slot -> [(sequence, player_id), ...] from per-player battingOrder strings."""
    _, team = _team_boxscore(raw, side)
    players = team.get("players")
    if not isinstance(players, dict):
        raise AdapterError("team players missing/invalid")
    chains: Dict[int, List[Tuple[int, str]]] = {i: [] for i in range(1, 10)}
    seen_codes = set()
    for rec in players.values():
        if not isinstance(rec, dict) or "battingOrder" not in rec:
            continue
        bo = rec.get("battingOrder")
        if bo in (None, ""):
            continue
        slot, sequence = _parse_batting_order_code(bo)
        if bo in seen_codes:
            raise AdapterError(f"duplicate battingOrder code {bo}")
        seen_codes.add(bo)
        person = rec.get("person")
        if not isinstance(person, dict) or "id" not in person:
            raise AdapterError(f"battingOrder {bo} missing person.id")
        chains[slot].append((sequence, _pid(person["id"])))
    for slot in chains:
        chains[slot].sort()
    return chains


def adapt_pregame_lineup_from_player_codes(
    raw: Dict[str, Any], side: str, provider: str, authority: str, fetched_at: str,
    *, snapshot_time: str, pregame_attested: bool
) -> List[BridgeSourceRecord]:
    """Emit confirmed lineup facts from an attested pregame boxscore snapshot.

    Fail closed if any substitution-sequence code is already present. That protects
    against accidentally labeling an in-game/final boxscore as pregame.
    """
    _common(provider, authority, fetched_at)
    _ts(snapshot_time, "snapshot_time")
    if pregame_attested is not True:
        raise AdapterError("boxscore snapshot is not attested pregame")
    gp, _ = _team_boxscore(raw, side)
    chains = extract_substitution_chain_for_audit(raw, side)
    if any(seq > 0 for entries in chains.values() for seq, _ in entries):
        raise AdapterError("pregame-attested snapshot contains substitution battingOrder codes")
    starters = extract_initial_lineup_for_audit(raw, side)
    out: List[BridgeSourceRecord] = []
    for slot in range(1, 10):
        pid = starters[slot]
        out.append(BridgeSourceRecord(
            source_id=f"{provider}_{gp}_{side}_slot{slot}_{snapshot_time}",
            fact_key=f"lineup_slot:{gp}:{side}:{slot}",
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


def compare_team_array_to_current_occupants(raw: Dict[str, Any], side: str) -> bool:
    """Audit-only consistency check for observed final/current state.

    Expected current occupant is the highest substitution sequence per slot. This does
    not authorize pregame use; it only characterizes the two simultaneously observed
    representations.
    """
    _, team = _team_boxscore(raw, side)
    order = team.get("battingOrder")
    if not isinstance(order, list) or len(order) != 9:
        raise AdapterError("team battingOrder must be a 9-player list")
    chains = extract_substitution_chain_for_audit(raw, side)
    current = []
    for slot in range(1, 10):
        if not chains[slot]:
            raise AdapterError(f"no battingOrder-coded player for slot {slot}")
        current.append(chains[slot][-1][1])
    return [_pid(x) for x in order] == current
