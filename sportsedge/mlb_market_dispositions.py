"""Canonical MLB 38-market scored-surface completeness.

Presentation only: guarantees RUN IT can report every catalog market explicitly,
including NO_MODEL/BLOCKED markets, without granting predictive or governance authority.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

CATALOG_PATH=Path("config/mlb_market_catalog.json")
_GROUPS=("game_markets","batter_markets","pitcher_markets","separate_protocol_markets","binary_markets_not_coerced","period_markets_not_coerced")

def canonical_mlb_markets(path: str|Path=CATALOG_PATH) -> tuple[str,...]:
    payload=json.loads(Path(path).read_text())
    markets=[]
    for group in _GROUPS:
        for market in payload.get(group,[]):
            name=str(market).strip().upper()
            if name and name not in markets:
                markets.append(name)
    return tuple(markets)

def market_dispositions(rows: Sequence[Mapping[str,Any]], *, catalog_path: str|Path=CATALOG_PATH) -> list[dict[str,Any]]:
    canonical=canonical_mlb_markets(catalog_path)
    by_market={m:[] for m in canonical}
    for raw in rows:
        market=str(raw.get("market") or "").strip().upper()
        if market in by_market:
            by_market[market].append(dict(raw))
    out=[]
    for market in canonical:
        candidates=by_market[market]
        if not candidates:
            out.append({"market":market,"status":"NO_MODEL","reason":"MARKET_NOT_SURFACED","quote_count":0,"best_confidence_score":0})
            continue
        actionable=[r for r in candidates if str(r.get("scored_status") or "").upper()=="ACTIONABLE"]
        statuses={str(r.get("scored_status") or "NO_MODEL").upper() for r in candidates}
        status="ACTIONABLE" if actionable else ("PASS" if "PASS" in statuses else ("BLOCKED" if "BLOCKED" in statuses else "NO_MODEL"))
        best=max((int(r.get("confidence_score") or 0) for r in candidates),default=0)
        out.append({"market":market,"status":status,"reason":"SURFACED","quote_count":len(candidates),"best_confidence_score":best})
    return out
