"""Research-only DK menu-to-canonical reconciliation; never prices markets."""
from __future__ import annotations

import json
from pathlib import Path

from sportsedge.canonical_coverage import resolve_market


def reconcile_dk_census(path: str | Path) -> dict:
    census = json.loads(Path(path).read_text(encoding="utf-8"))
    if census.get("schema") != "SPORTSEDGE_DK_INSPECTED_MENU_CENSUS_V1":
        raise ValueError("UNKNOWN_CENSUS_SCHEMA")
    rows = []
    for sport, spec in census.get("sports", {}).items():
        if sport not in ("MLB", "NFL", "CFB", "NBA", "CBB"):
            raise ValueError("UNSUPPORTED_SPORT")
        seen = set()
        for market in spec.get("markets", []):
            key = market.get("market_key")
            if not isinstance(key, str) or not key:
                raise ValueError("INVALID_MARKET_KEY")
            if key in seen:
                raise ValueError(f"DUPLICATE_MARKET_KEY:{sport}:{key}")
            seen.add(key)
            # No guessed aliases: only existing canonical registry decisions.
            resolution = resolve_market(sport, key)
            state = "NO_CANONICAL_ROUTE" if resolution is None else resolution["state"]
            rows.append({
                "sport": sport, "dk_market_key": key, "route_state": state,
                "canonical_market": resolution.get("market") if resolution else None,
                "blocker": resolution.get("blocker") if resolution else "NO_ROUTE",
                "validation_status": resolution.get("validation_status") if resolution else "NOT_RUN",
                "verified_probability": False, "play_authorized": False,
                "authority": "RESEARCH_ONLY_MENU_NOT_QUOTE",
            })
    return {
        "schema": "SPORTSEDGE_DK_CANONICAL_RECONCILIATION_V1",
        "rows": rows, "total": len(rows),
        "missing_sport_census": [s for s in ("MLB", "NFL", "CFB", "NBA", "CBB")
                                 if s not in census.get("sports", {})],
        "no_capture": True, "play_authorized": False,
    }
