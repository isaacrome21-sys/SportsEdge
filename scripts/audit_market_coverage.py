#!/usr/bin/env python3
"""Fail-closed audit of declared SportsEdge market surfaces."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _json(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def main() -> int:
    failures: list[str] = []
    report: dict[str, object] = {}

    mlb = _json("config/mlb_market_catalog.json")
    mlb_markets = []
    for key, value in mlb.items():
        if key == "schema_version":
            continue
        if isinstance(value, list) and all(isinstance(x, str) for x in value):
            mlb_markets.extend(value)
    if len(mlb_markets) != len(set(mlb_markets)):
        failures.append("MLB_MARKET_CATALOG_DUPLICATE")
    deployments = _json("config/deployments.json").get("markets", {})
    missing_deployments = sorted(set(mlb_markets) - set(deployments))
    undeclared_deployments = sorted(set(deployments) - set(mlb_markets))
    if missing_deployments:
        failures.append("MLB_MARKETS_MISSING_DEPLOYMENT_ROWS")
    if undeclared_deployments:
        failures.append("MLB_DEPLOYMENT_ROWS_NOT_IN_CATALOG")
    report["MLB"] = {
        "declared_market_count": len(set(mlb_markets)),
        "deployment_market_count": len(deployments),
        "missing_deployments": missing_deployments,
        "undeclared_deployments": undeclared_deployments,
        "eligible_market_count": sum(bool(row.get("eligible")) for row in deployments.values()),
    }

    football = _json("config/football_market_surface.json")
    football_rows = football.get("markets", [])
    keys = [(str(row.get("family")), str(row.get("market"))) for row in football_rows]
    if len(keys) != len(set(keys)):
        failures.append("FOOTBALL_MARKET_SURFACE_DUPLICATE")
    invalid_engines = []
    for row in football_rows:
        engines = row.get("engines")
        if not isinstance(engines, list) or not engines or any(x not in {"A", "B", "C"} for x in engines):
            invalid_engines.append(row.get("market"))
    if invalid_engines:
        failures.append("FOOTBALL_MARKET_ENGINE_CONTRACT_INVALID")
    report["FOOTBALL"] = {
        "sports": football.get("sports", []),
        "declared_market_count": len(keys),
        "families": sorted({family for family, _ in keys}),
        "invalid_engine_rows": invalid_engines,
    }

    for sport, path in (("PGA", "config/pga_market_surface.json"), ("UFC", "config/ufc_market_surface.json")):
        payload = _json(path)
        supported = [str(row.get("market")) for row in payload.get("supported_markets", [])]
        unsupported = [str(x) for x in payload.get("unsupported_without_new_engine", [])]
        if len(supported) != len(set(supported)):
            failures.append(f"{sport}_SUPPORTED_MARKET_DUPLICATE")
        overlap = sorted(set(supported).intersection(unsupported))
        if overlap:
            failures.append(f"{sport}_SUPPORTED_UNSUPPORTED_OVERLAP")
        report[sport] = {
            "supported_market_count": len(supported),
            "supported_markets": supported,
            "explicitly_unsupported_count": len(unsupported),
            "overlap": overlap,
        }

    report["LIVE"] = {
        "registry_present": (ROOT / "sportsedge/live_markets.py").is_file(),
        "status": "SHADOW_UNVALIDATED",
    }
    if not report["LIVE"]["registry_present"]:
        failures.append("LIVE_MARKET_REGISTRY_MISSING")

    payload = {"status": "PASS" if not failures else "FAIL", "failures": failures, "surfaces": report}
    out = ROOT / "artifacts/run_it/market_coverage.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
