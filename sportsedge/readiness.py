"""Machine-readable full-market readiness audit for SportsEdge MLB."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .deployments import load_registry
from .engine_registry import engine_registry
from .edge_floors import EdgeFloorError, require_frozen_edge_floor

DEFAULT_REGISTRY = Path("config/deployments.json")
DEFAULT_CATALOG = Path("config/mlb_market_catalog.json")
DEFAULT_FLOORS = Path("config/truth_gate_floors.json")
DEFAULT_VALIDATION = Path("config/mlb_validation_evidence.json")
DEFAULT_FEATURES = Path("config/mlb_market_feature_requirements.json")
DEFAULT_COLLECTORS = Path("config/mlb_collector_validation.json")
DEFAULT_FEATURE_REALIZATION = Path("config/mlb_feature_realization.json")
DEFAULT_BEHAVIORAL = Path("config/mlb_behavioral_disposition.json")
REQUIRED_DYNAMIC_COLLECTORS = ("mlb-game-context-refresh", "statcast-daily-refresh")


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_optional_json(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {"schema_version": 1, "markets": {}}
    return _load_json(p)


def _catalog_markets(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for key, rows in catalog.items():
        if key == "schema_version" or not isinstance(rows, list):
            continue
        group = key
        for row in rows:
            if isinstance(row, str):
                out[row] = {"group": group, "acquisition": True}
            elif isinstance(row, dict) and row.get("market"):
                out[str(row["market"])] = {"group": group, "acquisition": True, **row}
    nested = catalog.get("markets")
    if isinstance(nested, dict):
        for group, rows in nested.items():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, str):
                    out[row] = {"group": group, "acquisition": True}
                elif isinstance(row, dict) and row.get("market"):
                    out[str(row["market"])] = {"group": group, "acquisition": True, **row}
    return out


def _frozen_floor_markets(floors: dict[str, Any]) -> set[str]:
    truth_gate = floors.get("truth_gate")
    records = truth_gate.get("edge_floors") if isinstance(truth_gate, dict) else None
    if not isinstance(records, dict):
        return set()
    resolved = set()
    for market in records:
        try:
            require_frozen_edge_floor(market=market, config=floors)
        except EdgeFloorError:
            continue
        resolved.add(market)
    return resolved


def _validation_state(validation: dict[str, Any], market: str) -> tuple[bool, list[str], dict[str, str]]:
    required = validation.get("required_gates")
    if not isinstance(required, list) or not required or not all(isinstance(x, str) and x for x in required):
        raise ValueError("validation registry requires non-empty required_gates")
    markets = validation.get("markets")
    if not isinstance(markets, dict):
        raise ValueError("validation registry requires markets object")
    row = markets.get(market)
    if not isinstance(row, dict):
        return False, list(required), {}
    missing: list[str] = []
    statuses: dict[str, str] = {}
    for gate in required:
        value = row.get(gate)
        status = str(value.get("status", "MISSING") if isinstance(value, dict) else value or "MISSING").upper()
        statuses[gate] = status
        if status != "PASS":
            missing.append(gate)
    return not missing, missing, statuses


def _feature_contract_state(features: dict[str, Any], market: str) -> tuple[bool, list[str]]:
    global_required = features.get("global_required")
    families = features.get("feature_families")
    markets = features.get("markets")
    if not isinstance(global_required, list) or not global_required:
        raise ValueError("feature registry requires non-empty global_required")
    if not isinstance(families, dict) or not families:
        raise ValueError("feature registry requires feature_families")
    if not isinstance(markets, dict):
        raise ValueError("feature registry requires markets object")
    required_families = markets.get(market)
    if not isinstance(required_families, list) or not required_families:
        return False, []
    missing_defs = [name for name in required_families if name not in families]
    return not missing_defs, missing_defs


def _feature_realization_state(realization: dict[str, Any], market: str) -> tuple[bool, str, list[str]]:
    """Return whether the declared feature contract is proven active end-to-end."""
    markets = realization.get("markets")
    if not isinstance(markets, dict):
        return False, "UNVERIFIED", ["FEATURE_REALIZATION_REGISTRY_MISSING"]
    row = markets.get(market)
    if not isinstance(row, dict):
        return False, "UNVERIFIED", ["FEATURE_REALIZATION_UNATTESTED"]
    status = str(row.get("status", "UNVERIFIED")).upper()
    allowed = {"COMPLETE", "PARTIAL", "MINIMAL", "PLANNED", "UNVERIFIED"}
    if status not in allowed:
        raise ValueError(f"invalid feature realization status for {market}: {status}")
    gaps = row.get("gaps", [])
    if not isinstance(gaps, list):
        raise ValueError(f"feature realization gaps must be list for {market}")
    return status == "COMPLETE", status, [str(x) for x in gaps]


def _behavioral_state(behavioral: dict[str, Any], market: str) -> tuple[bool, str, str | None]:
    """Measured behavioral acceptance is independent of implementation/validation plumbing."""
    markets = behavioral.get("markets")
    if not isinstance(markets, dict):
        return False, "UNVERIFIED", "BEHAVIORAL_REGISTRY_MISSING"
    row = markets.get(market)
    if not isinstance(row, dict):
        return False, "UNVERIFIED", "BEHAVIORAL_UNATTESTED"
    status = str(row.get("status", "UNVERIFIED")).upper()
    allowed = {"KEEP_MEASURED", "WATCH", "FIX", "REBUILD", "UPSTREAM_MODEL_REVIEW", "UNVERIFIED", "UNMEASURED"}
    if status not in allowed:
        raise ValueError(f"invalid behavioral status for {market}: {status}")
    root_cause = row.get("root_cause")
    if root_cause is not None:
        root_cause = str(root_cause)
    return status == "KEEP_MEASURED", status, root_cause


def _collector_validation_state(collectors: dict[str, Any]) -> tuple[bool, list[str], dict[str, str]]:
    records = collectors.get("collectors")
    if not isinstance(records, dict):
        raise ValueError("collector validation registry requires collectors object")
    missing: list[str] = []
    statuses: dict[str, str] = {}
    for name in REQUIRED_DYNAMIC_COLLECTORS:
        row = records.get(name)
        status = str(row.get("status", "MISSING") if isinstance(row, dict) else "MISSING").upper()
        statuses[name] = status
        if status != "VALIDATED_COLLECTOR":
            missing.append(name)
    return not missing, missing, statuses


def audit_readiness(
    registry_path: str | Path = DEFAULT_REGISTRY,
    catalog_path: str | Path = DEFAULT_CATALOG,
    floors_path: str | Path = DEFAULT_FLOORS,
    validation_path: str | Path = DEFAULT_VALIDATION,
    features_path: str | Path = DEFAULT_FEATURES,
    collectors_path: str | Path = DEFAULT_COLLECTORS,
    feature_realization_path: str | Path = DEFAULT_FEATURE_REALIZATION,
    behavioral_path: str | Path = DEFAULT_BEHAVIORAL,
) -> dict[str, Any]:
    registry = load_registry(registry_path)
    engines = engine_registry()
    catalog = _catalog_markets(_load_json(catalog_path))
    frozen_floors = _frozen_floor_markets(_load_json(floors_path))
    validation = _load_json(validation_path)
    features = _load_json(features_path)
    realization = _load_optional_json(feature_realization_path)
    behavioral = _load_optional_json(behavioral_path)
    collector_complete, collector_missing, collector_status = _collector_validation_state(_load_json(collectors_path))

    if Path(registry_path) == DEFAULT_REGISTRY:
        all_markets = sorted(set(catalog) | set(registry["markets"]))
    else:
        all_markets = sorted(set(registry["markets"]))

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
        validation_complete, validation_missing, validation_status = _validation_state(validation, market)
        feature_contract_declared, missing_feature_definitions = _feature_contract_state(features, market)
        feature_realization_complete, feature_realization_status, feature_realization_gaps = _feature_realization_state(realization, market)
        behavioral_complete, behavioral_status, behavioral_root_cause = _behavioral_state(behavioral, market)

        blockers: list[str] = []
        classes: list[str] = []
        if not quote_supported:
            blockers.append("NO_QUOTE_ACQUISITION"); classes.append("ENGINEERING")
        if not registered:
            blockers.append("NOT_REGISTERED"); classes.append("ENGINEERING")
        if not has_engine:
            blockers.append("NO_RUNTIME_ENGINE"); classes.append("ENGINEERING")
        if not feature_contract_declared:
            blockers.append("NO_DECLARED_FEATURE_CONTRACT")
            blockers.extend(f"UNKNOWN_FEATURE_FAMILY_{x}" for x in missing_feature_definitions)
            classes.append("ENGINEERING")
        if not feature_realization_complete:
            blockers.append(f"FEATURE_REALIZATION_{feature_realization_status}")
            blockers.extend(f"FEATURE_GAP_{x}" for x in feature_realization_gaps)
            classes.append("ENGINEERING")
        if not behavioral_complete:
            blockers.append(f"BEHAVIORAL_{behavioral_status}")
            if behavioral_root_cause:
                blockers.append(f"BEHAVIORAL_CAUSE_{behavioral_root_cause}")
            classes.append("MODEL_VALIDATION")
        if not collector_complete:
            blockers.extend(f"COLLECTOR_{x.upper().replace('-', '_')}_NOT_VALIDATED" for x in collector_missing)
            classes.append("EVIDENCE")
        if not eligible:
            blockers.append("NOT_DEPLOYED"); classes.append("EVIDENCE" if has_engine else "ENGINEERING")
        if not has_floor:
            blockers.append("NO_FROZEN_EDGE_FLOOR"); classes.append("EVIDENCE")
        if not validation_complete:
            blockers.extend(f"VALIDATION_{gate.upper()}_PENDING" for gate in validation_missing)
            classes.append("EVIDENCE")
        if "fixture-backed ci attestation pending" in reason.lower():
            blockers.append("FIXTURE_CI_PENDING"); classes.append("EVIDENCE")
        if "quota" in reason.lower() or "provider" in reason.lower():
            classes.append("PROVIDER")

        classes = list(dict.fromkeys(classes))
        shadow_runnable = quote_supported and has_engine and feature_contract_declared
        runnable_live = shadow_runnable and collector_complete
        official = (
            runnable_live and feature_realization_complete and behavioral_complete and eligible
            and has_floor and validation_complete
        )
        rows.append({
            "market": market,
            "group": cat.get("group", "registry_only"),
            "quote_supported": quote_supported,
            "registered": registered,
            "runtime_engine": has_engine,
            "feature_contract_complete": feature_contract_declared,
            "feature_contract_declared": feature_contract_declared,
            "missing_feature_definitions": missing_feature_definitions,
            "feature_realization_complete": feature_realization_complete,
            "feature_realization_status": feature_realization_status,
            "feature_realization_gaps": feature_realization_gaps,
            "behavioral_complete": behavioral_complete,
            "behavioral_status": behavioral_status,
            "behavioral_root_cause": behavioral_root_cause,
            "collector_validation_complete": collector_complete,
            "collector_validation_status": collector_status,
            "collector_validation_missing": collector_missing,
            "eligible": eligible,
            "frozen_edge_floor": has_floor,
            "validation_complete": validation_complete,
            "validation_status": validation_status,
            "validation_missing": validation_missing,
            "stage": stage,
            "reason": reason,
            "blocker_classes": classes,
            "blockers": blockers,
            "shadow_runnable": shadow_runnable,
            "runnable_live": runnable_live,
            "official_bet_enabled": official,
        })

    return {
        "schema_version": 7,
        "collector_validation": {
            "complete": collector_complete,
            "status": collector_status,
            "missing": collector_missing,
        },
        "markets": rows,
        "summary": {
            "catalog_or_registered": len(rows),
            "quote_supported": sum(x["quote_supported"] for x in rows),
            "registered": sum(x["registered"] for x in rows),
            "runtime_engines": sum(x["runtime_engine"] for x in rows),
            "feature_contract_complete": sum(x["feature_contract_complete"] for x in rows),
            "feature_realization_complete": sum(x["feature_realization_complete"] for x in rows),
            "behavioral_complete": sum(x["behavioral_complete"] for x in rows),
            "collector_validation_complete": sum(x["collector_validation_complete"] for x in rows),
            "shadow_runnable": sum(x["shadow_runnable"] for x in rows),
            "runnable_live": sum(x["runnable_live"] for x in rows),
            "frozen_edge_floors": sum(x["frozen_edge_floor"] for x in rows),
            "validation_complete": sum(x["validation_complete"] for x in rows),
            "official_bet_enabled": sum(x["official_bet_enabled"] for x in rows),
            "engineering_blocked": sum("ENGINEERING" in x["blocker_classes"] for x in rows),
            "model_validation_blocked": sum("MODEL_VALIDATION" in x["blocker_classes"] for x in rows),
            "evidence_blocked": sum("EVIDENCE" in x["blocker_classes"] for x in rows),
        },
    }
