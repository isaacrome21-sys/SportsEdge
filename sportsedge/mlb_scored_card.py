"""MySpariEdge-style MLB RUN IT card presentation.

Pure presentation: ranks already-produced SportsEdge results. It never creates Model_P,
changes confidence, or grants governance authority. ACTIONABLE rows must carry the
versioned provenance emitted by ``score_mlb_edge``; unverified scores fail closed.
"""
from __future__ import annotations
from dataclasses import asdict, is_dataclass
from math import isfinite
from typing import Any, Mapping, Sequence

from .mlb_edge_score import MLB_EDGE_SCORE_PROVENANCE

_STATUS_ORDER={"ACTIONABLE":0,"PASS":1,"BLOCKED":2,"NO_MODEL":3}
_UNVERIFIED_REASON="UNVERIFIED_CONFIDENCE_PROVENANCE"


def _dict(row: Any) -> dict[str, Any]:
    if is_dataclass(row):
        return asdict(row)
    if isinstance(row, Mapping):
        return dict(row)
    raise TypeError("CARD_ROW_MUST_BE_MAPPING_OR_DATACLASS")


def _verified_model_score(row: Mapping[str, Any]) -> bool:
    if str(row.get("confidence_provenance") or "").strip().upper() != MLB_EDGE_SCORE_PROVENANCE:
        return False
    try:
        model_p=float(row["model_p"])
        market_p=float(row["market_p"])
        edge=float(row["edge"])
        ev=float(row["ev_per_dollar"])
    except (KeyError, TypeError, ValueError):
        return False
    if not all(isfinite(value) for value in (model_p, market_p, edge, ev)):
        return False
    if not (0 < model_p < 1 and 0 < market_p < 1):
        return False
    if abs((model_p-market_p)-edge) > 1e-9:
        return False
    reasons={str(reason).strip().upper() for reason in (row.get("reason_codes") or ())}
    return "POWER_V1_NO_VIG" in reasons


def build_mlb_scored_card(rows: Sequence[Any], *, actionable_only: bool=False) -> list[dict[str, Any]]:
    out=[]
    for raw in rows:
        row=_dict(raw)
        status=str(row.get("scored_status") or row.get("status") or "NO_MODEL").upper()
        score=int(row.get("confidence_score") or 0)
        edge=row.get("edge")
        ev=row.get("ev_per_dollar")
        verified=_verified_model_score(row)
        if status=="ACTIONABLE" and not verified:
            status="PASS"
            reasons=list(row.get("presentation_reason_codes") or ())
            if _UNVERIFIED_REASON not in reasons:
                reasons.append(_UNVERIFIED_REASON)
            row["presentation_reason_codes"]=tuple(reasons)
        if actionable_only and status!="ACTIONABLE":
            continue
        row["confidence_score"]=max(0,min(100,score))
        row["confidence_provenance"]=str(row.get("confidence_provenance") or "UNVERIFIED").strip().upper()
        row["confidence_verified"]=verified
        row["scored_status"]=status
        row["edge_pct"]=None if edge is None else round(100*float(edge),2)
        row["ev_pct"]=None if ev is None else round(100*float(ev),2)
        row["star_rating"]=0 if status in {"BLOCKED","NO_MODEL"} or not verified else min(5,max(1,(row["confidence_score"]+19)//20))
        out.append(row)
    return sorted(out,key=lambda r:(_STATUS_ORDER.get(r["scored_status"],9),-r["confidence_score"],-(r["ev_per_dollar"] if r.get("ev_per_dollar") is not None else -999)))


def top_mlb_edges(rows: Sequence[Any], *, limit: int=10) -> list[dict[str, Any]]:
    if limit < 1:
        raise ValueError("LIMIT_MUST_BE_POSITIVE")
    return build_mlb_scored_card(rows,actionable_only=True)[:limit]
