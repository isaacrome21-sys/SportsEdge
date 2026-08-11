"""Machine-readable deployment readiness audit for SportsEdge markets."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .deployments import load_registry
from .engine_registry import engine_registry


RUNTIME_COMPONENTS = {
    "HITS": ("engine", "live_lineup", "feature_bridge", "quote_bridge", "truth_gate"),
    "TOTAL_BASES": ("engine", "live_lineup", "feature_bridge", "quote_bridge", "truth_gate"),
}


def audit_readiness(registry_path: str | Path = "config/deployments.json") -> dict[str, Any]:
    registry = load_registry(registry_path)
    engines = engine_registry()
    rows = []
    for market, meta in registry["markets"].items():
        has_engine = market in engines
        components = RUNTIME_COMPONENTS.get(market, tuple())
        eligible = meta.get("eligible") is True
        stage = str(meta.get("stage", "UNKNOWN"))
        reason = str(meta.get("reason", ""))
        blockers: list[str] = []
        if not has_engine:
            blockers.append("NO_RUNTIME_ENGINE")
        if not components:
            blockers.append("NO_AUTOMATION_COMPONENT_MAP")
        if not eligible:
            blockers.append("NOT_DEPLOYED")
        if "fixture-backed CI attestation pending" in reason:
            blockers.append("FIXTURE_CI_PENDING")
        rows.append({
            "market": market,
            "stage": stage,
            "eligible": eligible,
            "runtime_engine": has_engine,
            "automation_components": list(components),
            "reason": reason,
            "blockers": blockers,
            "runnable_live": has_engine and bool(components),
            "official_bet_enabled": eligible and has_engine and bool(components),
        })
    return {
        "schema_version": 1,
        "markets": rows,
        "summary": {
            "registered": len(rows),
            "runtime_engines": sum(x["runtime_engine"] for x in rows),
            "runnable_live": sum(x["runnable_live"] for x in rows),
            "official_bet_enabled": sum(x["official_bet_enabled"] for x in rows),
        },
    }
