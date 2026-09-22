"""Strict same-book/same-line pairing for MLB two-sided markets."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

N_WAY_MARKETS=frozenset({"FIRST_HOME_RUN"})
_OPPOSITES={"OVER":"UNDER","UNDER":"OVER","YES":"NO","NO":"YES","HOME":"AWAY","AWAY":"HOME"}
# Frozen paired-side retrieval skew (seconds). Sides further apart are not a pair.
MAX_PAIRED_SKEW_SECONDS=30.0

def _retrieved_at(row: Mapping[str,Any]) -> datetime | None:
    raw=row.get("quote_retrieved_at") or row.get("retrieved_at")
    if not raw:
        return None
    if isinstance(raw,datetime):
        stamp=raw
    else:
        try:
            stamp=datetime.fromisoformat(str(raw).replace("Z","+00:00"))
        except (TypeError,ValueError):
            return None
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        return None
    return stamp.astimezone(timezone.utc)

def pair_opposite_odds(rows: Sequence[Any]) -> list[dict[str,Any]]:
    material=[]
    for raw in rows:
        row=dict(raw) if isinstance(raw,Mapping) else dict(vars(raw))
        material.append(row)
    for i,row in enumerate(material):
        market=str(row.get("market") or "").upper()
        if market in N_WAY_MARKETS or row.get("opposite_odds") is not None:
            continue
        side=str(row.get("side") or "").upper()
        opposite=_OPPOSITES.get(side)
        if not opposite:
            continue
        stamp=_retrieved_at(row)
        if stamp is None:
            # No valid timestamp -> skew cannot be proven -> never paired.
            continue
        matches=[]
        for j,other in enumerate(material):
            if i==j: continue
            if str(other.get("game_id"))!=str(row.get("game_id")): continue
            if str(other.get("market") or "").upper()!=market: continue
            if str(other.get("book_key") or other.get("sportsbook") or "")!=str(row.get("book_key") or row.get("sportsbook") or ""): continue
            if other.get("line")!=row.get("line"): continue
            if str(other.get("entity_id") or "")!=str(row.get("entity_id") or ""): continue
            if str(other.get("side") or "").upper()!=opposite: continue
            if other.get("american_odds") is None: continue
            other_stamp=_retrieved_at(other)
            if other_stamp is None or abs((other_stamp-stamp).total_seconds())>MAX_PAIRED_SKEW_SECONDS: continue
            matches.append(other)
        if len(matches)==1:
            row["opposite_odds"]=matches[0]["american_odds"]
    return material
