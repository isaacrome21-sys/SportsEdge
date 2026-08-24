"""Executable acceptance matrix for the complete SportsEdge MLB market surface.

This module deliberately does not create a second behavioral/evidence registry.
Acceptance requirements live in config/mlb_acceptance_matrix.json; current state is
read from the canonical catalog, deployment, behavioral, feature-realization, and
validation-evidence registries at runtime.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .engine_registry import engine_registry

DEFAULT_MATRIX = Path("config/mlb_acceptance_matrix.json")
DEFAULT_CATALOG = Path("config/mlb_market_catalog.json")
DEFAULT_DEPLOYMENTS = Path("config/deployments.json")
DEFAULT_BEHAVIORAL = Path("config/mlb_behavioral_disposition.json")
DEFAULT_VALIDATION = Path("config/mlb_validation_evidence.json")
DEFAULT_REALIZATION = Path("config/mlb_feature_realization.json")


class MLBAcceptanceMatrixError(ValueError):
    pass


def _load(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise MLBAcceptanceMatrixError(f"expected object: {path}")
    return payload


def _catalog_markets(payload: Mapping[str, Any]) -> set[str]:
    markets: set[str] = set()
    for key, rows in payload.items():
        if key == "schema_version" or not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, str) and row:
                markets.add(row)
            elif isinstance(row, Mapping) and row.get("market"):
                markets.add(str(row["market"]))
    return markets


def _family_index(matrix: Mapping[str, Any]) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    families = matrix.get("families")
    if not isinstance(families, Mapping) or not families:
        raise MLBAcceptanceMatrixError("acceptance matrix requires families")
    index: dict[str, str] = {}
    normalized: dict[str, dict[str, Any]] = {}
    for family, raw in families.items():
        if not isinstance(raw, Mapping):
            raise MLBAcceptanceMatrixError(f"family {family} must be object")
        rows = raw.get("markets")
        structural = raw.get("structural_checks")
        settlement = raw.get("settlement_checks")
        if not isinstance(rows, list) or not rows:
            raise MLBAcceptanceMatrixError(f"family {family} requires markets")
        if not isinstance(structural, list) or not structural:
            raise MLBAcceptanceMatrixError(f"family {family} requires structural_checks")
        if not isinstance(settlement, list) or not settlement:
            raise MLBAcceptanceMatrixError(f"family {family} requires settlement_checks")
        normalized[str(family)] = {
            "structural_checks": [str(x) for x in structural],
            "settlement_checks": [str(x) for x in settlement],
        }
        for market in rows:
            name = str(market)
            if name in index:
                raise MLBAcceptanceMatrixError(
                    f"market assigned to multiple acceptance families: {name} ({index[name]}, {family})"
                )
            index[name] = str(family)
    return index, normalized


def build_acceptance_matrix(
    *,
    matrix_path: str | Path = DEFAULT_MATRIX,
    catalog_path: str | Path = DEFAULT_CATALOG,
    deployments_path: str | Path = DEFAULT_DEPLOYMENTS,
    behavioral_path: str | Path = DEFAULT_BEHAVIORAL,
    validation_path: str | Path = DEFAULT_VALIDATION,
    realization_path: str | Path = DEFAULT_REALIZATION,
) -> dict[str, Any]:
    matrix = _load(matrix_path)
    catalog = _load(catalog_path)
    deployments = _load(deployments_path)
    behavioral = _load(behavioral_path)
    validation = _load(validation_path)
    realization = _load(realization_path)

    dimensions = matrix.get("dimensions")
    if not isinstance(dimensions, list) or len(set(map(str, dimensions))) != len(dimensions):
        raise MLBAcceptanceMatrixError("acceptance dimensions must be a unique list")

    catalog_markets = _catalog_markets(catalog)
    if not catalog_markets:
        raise MLBAcceptanceMatrixError("catalog contains no markets")
    family_by_market, family_defs = _family_index(matrix)
    assigned = set(family_by_market)
    if assigned != catalog_markets:
        missing = sorted(catalog_markets - assigned)
        extra = sorted(assigned - catalog_markets)
        raise MLBAcceptanceMatrixError(
            f"acceptance family coverage mismatch missing={missing} extra={extra}"
        )

    dep_markets = deployments.get("markets")
    beh_markets = behavioral.get("markets")
    val_markets = validation.get("markets")
    real_markets = realization.get("markets")
    required_gates = validation.get("required_gates")
    if not all(isinstance(x, Mapping) for x in (dep_markets, beh_markets, val_markets, real_markets)):
        raise MLBAcceptanceMatrixError("canonical registries require markets objects")
    if not isinstance(required_gates, list) or not required_gates:
        raise MLBAcceptanceMatrixError("validation registry requires required_gates")

    for label, registry_markets in (
        ("deployments", dep_markets),
        ("behavioral", beh_markets),
        ("validation", val_markets),
        ("feature_realization", real_markets),
    ):
        names = set(map(str, registry_markets))
        if names != catalog_markets:
            raise MLBAcceptanceMatrixError(
                f"{label} market coverage mismatch missing={sorted(catalog_markets - names)} "
                f"extra={sorted(names - catalog_markets)}"
            )

    engines = engine_registry()
    rows: list[dict[str, Any]] = []
    for market in sorted(catalog_markets):
        family = family_by_market[market]
        family_def = family_defs[family]
        dep = dict(dep_markets[market])
        beh = dict(beh_markets[market])
        val = dict(val_markets[market])
        real = dict(real_markets[market])

        gate_status: dict[str, str] = {}
        missing_gates: list[str] = []
        for gate in required_gates:
            raw = val.get(gate)
            status = str(raw.get("status", "MISSING") if isinstance(raw, Mapping) else raw or "MISSING").upper()
            gate_status[str(gate)] = status
            if status != "PASS":
                missing_gates.append(str(gate))

        behavioral_status = str(beh.get("status", "UNVERIFIED")).upper()
        realization_status = str(real.get("status", "UNVERIFIED")).upper()
        runtime_engine = market in engines
        registered = market in dep_markets
        validation_complete = not missing_gates
        behavioral_complete = behavioral_status == "KEEP_MEASURED"
        realization_complete = realization_status == "COMPLETE"
        eligible = dep.get("eligible") is True

        rows.append({
            "market": market,
            "acceptance_family": family,
            "requirements": {
                "runtime_contract": ["REGISTERED_RUNTIME_ENGINE", "FEATURE_CONTRACT_REALIZED"],
                "structural_behavior": list(family_def["structural_checks"]),
                "settlement_semantics": list(family_def["settlement_checks"]),
                "evidence_gates": [str(x) for x in required_gates],
            },
            "current_state": {
                "runtime_engine": runtime_engine,
                "registered": registered,
                "deployment_stage": str(dep.get("stage", "UNREGISTERED")),
                "eligible": eligible,
                "behavioral_status": behavioral_status,
                "remediation_state": beh.get("remediation_state"),
                "feature_realization_status": realization_status,
                "validation_status": gate_status,
                "validation_missing": missing_gates,
            },
            "acceptance_complete": bool(
                runtime_engine
                and registered
                and eligible
                and behavioral_complete
                and realization_complete
                and validation_complete
            ),
        })

    return {
        "schema_version": 1,
        "policy": dict(matrix.get("policy") or {}),
        "dimensions": [str(x) for x in dimensions],
        "market_count": len(rows),
        "markets": rows,
        "summary": {
            "runtime_engine_present": sum(bool(r["current_state"]["runtime_engine"]) for r in rows),
            "behaviorally_measured": sum(r["current_state"]["behavioral_status"] == "KEEP_MEASURED" for r in rows),
            "feature_realization_complete": sum(r["current_state"]["feature_realization_status"] == "COMPLETE" for r in rows),
            "validation_complete": sum(not r["current_state"]["validation_missing"] for r in rows),
            "acceptance_complete": sum(bool(r["acceptance_complete"]) for r in rows),
        },
    }
