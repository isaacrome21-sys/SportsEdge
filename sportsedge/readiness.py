"""Machine-readable full-market readiness audit for SportsEdge MLB."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .deployments import load_registry
from .engine_registry import engine_registry

DEFAULT_CATALOG = Path("config/mlb_market_catalog.json")
DEFAULT_FLOORS = Path("config/truth_gate_floors.json")

# Acquisition classes from the canonical catalog. These describe parser/quote
# support only; they do not imply model or betting eligibility.

def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _catalog_markets(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for group, rows in (catalog.get("markets") or {}).items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, str):
                out[row] = {"group": group, "acquisition": True}
            elif isinstance(row, dict) and row.get("market"):
                out[str(row["market"])] = {"group": group, **row}
    return out


def _frozen_floor_markets(floors: dict[str, Any]) -> set[str]:
    records = (((floors.get("truth_gate") or {}).get("edge_floors")) or {})
    return {
        str(market)
        for market, meta in records.items()
        if isinstance(meta, dict)
        and str(meta.get("status", "")).upper() == "FROZEN"
        and isinstance(meta.get("value"), (int, float))
        and not isinstance(meta.get("value"), bool)
        and float(meta["value"]) > 0.0
    }


def audit_readiness(
    registry_path: str | Path = "config/deployments.json",
    catalog_path: str | Path = DEFAULT_CATALOG,
    floors_path: str | Path = DEFAULT_FLOORS,
) -> dict[str, Any]:
    registry = load_registry(registry_path)
    engines = engine_registry()
    catalog = _catalog_markets(_load_json(catalog_path))
    frozen_floors = _frozen_floor_markets(_load_json(floors_path))

    all_markets = sorted(set(catalog) | set(registry["markets"]))
    rows: list[dict[str, Any]] = []
    for market in all_markets:
        meta = registry["markets"].get(market, {})
        cat = catalog.get(market, {})
        registered = market in registry["markets"]
        quote_supported = bool(cat) and cat.get("acquisition", True) is not False
        has_engine = market in engines
        eligible = meta.get("eligible") is True
        has_floor = market in frozen_floors
        stage = str(meta.get("stage", "UNREGISTERED"))
        reason = str(meta.get("reason", "market absent from deployment registry"))

        blockers: list[str] = []
        classes: list[str] = []
        if not quote_supported:
            blockers.append("NO_QUOTE_ACQUISITION")
            classes.append("ENGINEERING")
        if not registered:
            blockers.append("NOT_REGISTERED")
            classes.append("ENGINEERING")
        if not has_engine:
            blockers.append("NO_RUNTIME_ENGINE")
            classes.append("ENGINEERING")
        if not eligible:
            blockers.append("NOT_DEPLOYED")
            classes.append("EVIDENCE" if has_engine else "ENGINEERING")
        if not has_floor:
            blockers.append("NO_FROZEN_EDGE_FLOOR")
            classes.append("EVIDENCE")
        if "quota" in reason.lower() or "provider" in reason.lower():
            classes.append("PROVIDER")

        classes = list(dict.fromkeys(classes))
        rows.append({
            "market": market,
            "group": cat.get("group", "registry_only"),
            "quote_supported": quote_supported,
            "registered": registered,
            "runtime_engine": has_engine,
            "eligible": eligible,
            "frozen_edge_floor": has_floor,
            "stage": stage,
            "reason": reason,
            "blocker_classes": classes,
            "blockers": blockers,
            "shadow_runnable": quote_supported and has_engine,
            "official_bet_enabled": quote_supported and has_engine and eligible and has_floor,
        })

    return {
        "schema_version": 2,
        "markets": rows,
        "summary": {
            "catalog_or_registered": len(rows),
            "quote_supported": sum(x["quote_supported"] for x in rows),
            "registered": sum(x["registered"] for x in rows),
            "runtime_engines": sum(x["runtime_engine"] for x in rows),
            "shadow_runnable": sum(x["shadow_runnable"] for x in rows),
            "frozen_edge_floors": sum(x["frozen_edge_floor"] for x in rows),
            "official_bet_enabled": sum(x["official_bet_enabled"] for x in rows),
            "engineering_blocked": sum("ENGINEERING" in x["blocker_classes"] for x in rows),
            "evidence_blocked": sum("EVIDENCE" in x["blocker_classes"] for x in rows),
        },
    }
