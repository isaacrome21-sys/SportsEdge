"""Strict same-book pairing for MLB two-sided markets.

Moneyline and run-line sides are usually team names, not HOME/AWAY tokens.
Run-line numbers are also opposite-signed. Totals still pair on the exact line.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

N_WAY_MARKETS=frozenset({"FIRST_HOME_RUN"})
TEAM_MARKETS=frozenset({"MONEYLINE","ML","RUN_LINE","RUNLINE","SPREAD","SPREADS"})
TOTAL_MARKETS=frozenset({"TOTAL","TOTALS","TEAM_TOTAL","F5_TOTAL","F5_TEAM_TOTAL"})
_OPPOSITES={"OVER":"UNDER","UNDER":"OVER","YES":"NO","NO":"YES","HOME":"AWAY","AWAY":"HOME"}
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


def _norm_market(row: Mapping[str,Any]) -> str:
    return str(row.get("market") or "").upper().replace(" ","_")


def _side(row: Mapping[str,Any]) -> str:
    return str(row.get("side") or row.get("selection") or "").strip().upper()


def _book(row: Mapping[str,Any]) -> str:
    return str(row.get("book_key") or row.get("sportsbook") or row.get("book") or "").strip().upper()


def _line_key(row: Mapping[str,Any], market: str) -> tuple:
    raw=row.get("line")
    if raw is None:
        return (None,)
    try:
        line=float(raw)
    except (TypeError,ValueError):
        return ("raw", raw)
    if market in TEAM_MARKETS:
        return ("abs", round(abs(line), 4))
    return ("exact", round(line, 4))


def _team_pair(a: Mapping[str,Any], b: Mapping[str,Any]) -> bool:
    sa, sb = _side(a), _side(b)
    if not sa or not sb or sa == sb:
        return False
    if _OPPOSITES.get(sa) == sb:
        return True
    homes={str(a.get("home") or "").strip().upper(), str(b.get("home") or "").strip().upper()}
    aways={str(a.get("away") or "").strip().upper(), str(b.get("away") or "").strip().upper()}
    homes.discard("")
    aways.discard("")
    if len(homes)==1 and len(aways)==1:
        home=next(iter(homes)); away=next(iter(aways))
        return {sa, sb} == {home, away}
    # Last resort for team markets only: two distinct non-total sides.
    reserved=set(_OPPOSITES) | {"OVER","UNDER","YES","NO"}
    return sa not in reserved and sb not in reserved


def _is_complement(a: Mapping[str,Any], b: Mapping[str,Any]) -> bool:
    market=_norm_market(a)
    if _norm_market(b) != market or market in N_WAY_MARKETS:
        return False
    if str(a.get("game_id")) != str(b.get("game_id")):
        return False
    if _book(a) != _book(b) or not _book(a):
        return False
    if _line_key(a, market) != _line_key(b, market):
        return False
    if str(a.get("entity_id") or "") != str(b.get("entity_id") or ""):
        return False
    sa, sb = _side(a), _side(b)
    if market in TEAM_MARKETS:
        return _team_pair(a, b)
    return _OPPOSITES.get(sa) == sb


def pair_opposite_odds(rows: Sequence[Any]) -> list[dict[str,Any]]:
    material=[]
    for raw in rows:
        row=dict(raw) if isinstance(raw,Mapping) else dict(vars(raw))
        material.append(row)
    for i,row in enumerate(material):
        market=_norm_market(row)
        if market in N_WAY_MARKETS or row.get("opposite_odds") is not None:
            continue
        stamp=_retrieved_at(row)
        if stamp is None:
            continue
        matches=[]
        for j,other in enumerate(material):
            if i==j:
                continue
            if not _is_complement(row, other):
                continue
            if other.get("american_odds") is None:
                continue
            other_stamp=_retrieved_at(other)
            if other_stamp is None or abs((other_stamp-stamp).total_seconds())>MAX_PAIRED_SKEW_SECONDS:
                continue
            matches.append(other)
        if len(matches)==1:
            row["opposite_odds"]=matches[0]["american_odds"]
    return material
