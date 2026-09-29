"""Executable acceptance matrix for the complete SportsEdge MLB market surface.

This module deliberately does not create a second behavioral/evidence registry.
Acceptance requirements live in config/mlb_acceptance_matrix.json; current state is
read from the canonical catalog, acquisition surface, deployment, behavioral,
feature-realization, and validation-evidence registries at runtime.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping

from .engine_registry import engine_registry

DEFAULT_MATRIX = Path("config/mlb_acceptance_matrix.json")
DEFAULT_CATALOG = Path("config/mlb_market_catalog.json")
DEFAULT_SURFACE = Path("config/mlb_market_surface.json")
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


def _surface_index(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows = payload.get("markets")
    if not isinstance(rows, list) or not rows:
        raise MLBAcceptanceMatrixError("market surface requires markets list")

    index: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise MLBAcceptanceMatrixError("market surface rows must be objects")
        market = str(raw.get("market") or "").strip()
        if not market:
            raise MLBAcceptanceMatrixError("market surface row requires market")
        if market in index:
            raise MLBAcceptanceMatrixError(f"duplicate market in market surface: {market}")

        scope = str(raw.get("scope") or "").strip()
        route = str(raw.get("acquisition_route") or "").strip()
        terminal = str(raw.get("terminal_if_absent") or "").strip()
        availability = str(raw.get("declared_availability") or "").upper()
        window = raw.get("availability_window")
        if not scope or not route or not terminal:
            raise MLBAcceptanceMatrixError(f"incomplete acquisition contract for {market}")
        if not isinstance(raw.get("provider_expected"), bool):
            raise MLBAcceptanceMatrixError(f"provider_expected must be boolean for {market}")
        if not isinstance(raw.get("retry_eligible"), bool):
            raise MLBAcceptanceMatrixError(f"retry_eligible must be boolean for {market}")
        if availability not in {"AVAILABLE", "UNAVAILABLE"}:
            raise MLBAcceptanceMatrixError(
                f"invalid declared_availability for {market}: {availability or 'MISSING'}"
            )
        if not isinstance(window, Mapping):
            raise MLBAcceptanceMatrixError(f"availability_window must be object for {market}")
        for field in (
            "opens_minutes_before_first_pitch",
            "expected_by_minutes_before_first_pitch",
        ):
            value = window.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise MLBAcceptanceMatrixError(
                    f"{field} must be a non-negative integer for {market}"
                )

        index[market] = dict(raw)
    return index


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


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _sha256_like(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _historical_pit_pass(raw: Any) -> bool:
    """Require timestamp/provenance binding for historical PIT evidence.

    A bare PASS label is never enough. The observation must be source-hash bound,
    demonstrably available no later than the decision time, explicitly non-retroactive,
    and complete for every input class the evidence record declares as required. This
    lets market-specific protocols require lineup and/or starting-pitcher binding without
    pretending every MLB market consumes identical inputs.
    """
    if not isinstance(raw, Mapping) or str(raw.get("status", "")).upper() != "PASS":
        return False
    binding = raw.get("pit_binding")
    if not isinstance(binding, Mapping):
        return False
    observed_at = _parse_utc(binding.get("observed_at_utc"))
    decision_at = _parse_utc(binding.get("decision_at_utc"))
    if observed_at is None or decision_at is None or observed_at > decision_at:
        return False
    if binding.get("retroactive_point_in_time_claim") is not False:
        return False
    if not _sha256_like(binding.get("source_snapshot_sha256")):
        return False

    required = binding.get("required_input_classes", [])
    bound_inputs = binding.get("bound_inputs", {})
    if not isinstance(required, list) or not isinstance(bound_inputs, Mapping):
        return False
    for item in required:
        name = str(item)
        row = bound_inputs.get(name)
        if not name or not isinstance(row, Mapping):
            return False
        row_observed = _parse_utc(row.get("observed_at_utc"))
        if row_observed is None or row_observed > decision_at:
            return False
        if not str(row.get("identity", "")).strip():
            return False
        row_hash = row.get("source_snapshot_sha256", binding.get("source_snapshot_sha256"))
        if not _sha256_like(row_hash):
            return False
    return True


def _acceptance_blockers(
    *,
    runtime_engine: bool,
    registered: bool,
    eligible: bool,
    behavioral_status: str,
    realization_status: str,
    gate_status: Mapping[str, str],
) -> list[str]:
    blockers: list[str] = []
    if not runtime_engine:
        blockers.append("RUNTIME_ENGINE_MISSING")
    if not registered:
        blockers.append("DEPLOYMENT_REGISTRATION_MISSING")
    if not eligible:
        blockers.append("DEPLOYMENT_NOT_ELIGIBLE")
    if behavioral_status != "KEEP_MEASURED":
        blockers.append(f"BEHAVIORAL:{behavioral_status}")
    if realization_status != "COMPLETE":
        blockers.append(f"FEATURE_REALIZATION:{realization_status}")
    for gate, status in gate_status.items():
        if status != "PASS":
            blockers.append(f"VALIDATION:{gate}:{status}")
    return blockers


def build_acceptance_matrix(
    *,
    matrix_path: str | Path = DEFAULT_MATRIX,
    catalog_path: str | Path = DEFAULT_CATALOG,
    surface_path: str | Path = DEFAULT_SURFACE,
    deployments_path: str | Path = DEFAULT_DEPLOYMENTS,
    behavioral_path: str | Path = DEFAULT_BEHAVIORAL,
    validation_path: str | Path = DEFAULT_VALIDATION,
    realization_path: str | Path = DEFAULT_REALIZATION,
) -> dict[str, Any]:
    matrix = _load(matrix_path)
    catalog = _load(catalog_path)
    surface = _load(surface_path)
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

    surface_by_market = _surface_index(surface)
    surface_markets = set(surface_by_market)
    if surface_markets != catalog_markets:
        missing = sorted(catalog_markets - surface_markets)
        extra = sorted(surface_markets - catalog_markets)
        raise MLBAcceptanceMatrixError(
            f"market surface coverage mismatch missing={missing} extra={extra}"
        )

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
        surface_row = dict(surface_by_market[market])
        dep = dict(dep_markets[market])
        beh = dict(beh_markets[market])
        val = dict(val_markets[market])
        real = dict(real_markets[market])

        gate_status: dict[str, str] = {}
        missing_gates: list[str] = []
        for gate in required_gates:
            gate_name = str(gate)
            raw = val.get(gate)
            if gate_name == "historical_point_in_time":
                raw_status = str(
                    raw.get("status", "MISSING") if isinstance(raw, Mapping) else raw or "MISSING"
                ).upper()
                status = (
                    "PASS"
                    if _historical_pit_pass(raw)
                    else ("INVALID_PIT_BINDING" if raw_status == "PASS" else raw_status)
                )
            else:
                status = str(
                    raw.get("status", "MISSING") if isinstance(raw, Mapping) else raw or "MISSING"
                ).upper()
            gate_status[gate_name] = status
            if status != "PASS":
                missing_gates.append(gate_name)

        behavioral_status = str(beh.get("status", "UNVERIFIED")).upper()
        realization_status = str(real.get("status", "UNVERIFIED")).upper()
        runtime_engine = market in engines
        registered = market in dep_markets
        eligible = dep.get("eligible") is True
        blockers = _acceptance_blockers(
            runtime_engine=runtime_engine,
            registered=registered,
            eligible=eligible,
            behavioral_status=behavioral_status,
            realization_status=realization_status,
            gate_status=gate_status,
        )

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
                "acquisition": {
                    "scope": str(surface_row["scope"]),
                    "provider_expected": bool(surface_row["provider_expected"]),
                    "retry_eligible": bool(surface_row["retry_eligible"]),
                    "terminal_if_absent": str(surface_row["terminal_if_absent"]),
                    "acquisition_route": str(surface_row["acquisition_route"]),
                    "declared_availability": str(surface_row["declared_availability"]).upper(),
                    "availability_window": dict(surface_row["availability_window"]),
                },
            },
            "acceptance_blockers": blockers,
            "acceptance_complete": not blockers,
        })

    declared_available = sum(
        r["current_state"]["acquisition"]["declared_availability"] == "AVAILABLE" for r in rows
    )
    provider_expected = sum(
        bool(r["current_state"]["acquisition"]["provider_expected"]) for r in rows
    )
    return {
        "schema_version": 1,
        "policy": dict(matrix.get("policy") or {}),
        "dimensions": [str(x) for x in dimensions],
        "inventory_complete": True,
        "market_count": len(rows),
        "surface_market_count": len(surface_by_market),
        "markets": rows,
        "summary": {
            "surface_provider_expected": provider_expected,
            "surface_declared_available": declared_available,
            "surface_declared_unavailable": len(rows) - declared_available,
            "runtime_engine_present": sum(bool(r["current_state"]["runtime_engine"]) for r in rows),
            "behaviorally_measured": sum(
                r["current_state"]["behavioral_status"] == "KEEP_MEASURED" for r in rows
            ),
            "feature_realization_complete": sum(
                r["current_state"]["feature_realization_status"] == "COMPLETE" for r in rows
            ),
            "validation_complete": sum(
                not r["current_state"]["validation_missing"] for r in rows
            ),
            "acceptance_complete": sum(bool(r["acceptance_complete"]) for r in rows),
            "acceptance_blocked": sum(not r["acceptance_complete"] for r in rows),
        },
    }
