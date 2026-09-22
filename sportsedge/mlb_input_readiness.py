"""Market-specific MLB scored-input readiness.

This is a presentation safety layer. It consumes explicit feature-family readiness
when supplied and never infers missing model evidence as present.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Mapping

REQ_PATH=Path("config/mlb_market_feature_requirements.json")

def required_feature_families(market: str, path: str|Path=REQ_PATH) -> tuple[str,...]:
    payload=json.loads(Path(path).read_text())
    return tuple(payload.get("markets",{}).get(str(market).upper(),()))

def scored_input_readiness(row: Mapping[str,Any], *, path: str|Path=REQ_PATH) -> tuple[bool,tuple[str,...]]:
    market=str(row.get("market") or "").upper()
    required=required_feature_families(market,path)
    # Upstream BLOCKED is always authoritative.
    if str(row.get("bet_status") or "").upper()=="BLOCKED":
        return False,("UPSTREAM_BLOCKED",)
    readiness=row.get("feature_family_readiness")
    if readiness is None:
        # Legacy engines have already gated required inputs upstream; do not invent
        # family-level failures when they did not emit family readiness metadata.
        return True,()
    if not isinstance(readiness,Mapping):
        return False,("INVALID_FEATURE_READINESS",)
    missing=tuple(name for name in required if readiness.get(name) is not True)
    return (not missing,missing)
