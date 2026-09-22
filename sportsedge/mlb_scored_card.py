"""MySpariEdge-style MLB RUN IT card presentation.

Pure presentation: ranks already-produced SportsEdge results. It never creates Model_P,
changes confidence, or grants governance authority.
"""
from __future__ import annotations
from dataclasses import asdict, is_dataclass
from typing import Any, Mapping, Sequence

_STATUS_ORDER={"ACTIONABLE":0,"PASS":1,"BLOCKED":2,"NO_MODEL":3}

def _dict(row: Any) -> dict[str, Any]:
    if is_dataclass(row):
        return asdict(row)
    if isinstance(row, Mapping):
        return dict(row)
    raise TypeError("CARD_ROW_MUST_BE_MAPPING_OR_DATACLASS")

def build_mlb_scored_card(rows: Sequence[Any], *, actionable_only: bool=False) -> list[dict[str, Any]]:
    out=[]
    for raw in rows:
        row=_dict(raw)
        status=str(row.get("scored_status") or "NO_MODEL").upper()
        if actionable_only and status!="ACTIONABLE":
            continue
        score=int(row.get("confidence_score") or 0)
        edge=row.get("edge")
        ev=row.get("ev_per_dollar")
        row["confidence_score"]=max(0,min(100,score))
        row["scored_status"]=status
        row["edge_pct"]=None if edge is None else round(100*float(edge),2)
        row["ev_pct"]=None if ev is None else round(100*float(ev),2)
        row["star_rating"]=0 if status in {"BLOCKED","NO_MODEL"} else min(5,max(1,(row["confidence_score"]+19)//20))
        out.append(row)
    return sorted(out,key=lambda r:(_STATUS_ORDER.get(r["scored_status"],9),-r["confidence_score"],-(r["ev_per_dollar"] if r.get("ev_per_dollar") is not None else -999)))

def top_mlb_edges(rows: Sequence[Any], *, limit: int=10) -> list[dict[str, Any]]:
    if limit < 1:
        raise ValueError("LIMIT_MUST_BE_POSITIVE")
    return build_mlb_scored_card(rows,actionable_only=True)[:limit]
