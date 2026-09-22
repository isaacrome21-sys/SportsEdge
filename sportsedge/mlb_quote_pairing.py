"""Strict same-book/same-line pairing for MLB two-sided markets."""
from __future__ import annotations
from typing import Any, Mapping, Sequence

N_WAY_MARKETS=frozenset({"FIRST_HOME_RUN"})
_OPPOSITES={"OVER":"UNDER","UNDER":"OVER","YES":"NO","NO":"YES","HOME":"AWAY","AWAY":"HOME"}

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
            matches.append(other)
        if len(matches)==1:
            row["opposite_odds"]=matches[0]["american_odds"]
    return material
