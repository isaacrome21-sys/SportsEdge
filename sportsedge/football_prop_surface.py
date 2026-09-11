"""Runtime resolver for the authoritative football player-prop engine surface."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, Mapping

from sportsedge.football_prop_extended_run_machine import PROVIDER_MARKETS

DEFAULT_PROP_SURFACE = Path("config/football_prop_engine_surface.json")
EXPECTED_SCHEMA = "FOOTBALL_PROP_ENGINE_SURFACE_V1"
EXPECTED_LIBRARY_ENTRYPOINT = "sportsedge.football_prop_readiness:run_football_props_ready"


class FootballPropSurfaceError(ValueError):
    pass


def load_prop_surface(path: str | Path = DEFAULT_PROP_SURFACE) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise FootballPropSurfaceError("FOOTBALL_PROP_ENGINE_SURFACE_UNREADABLE") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != EXPECTED_SCHEMA:
        raise FootballPropSurfaceError("FOOTBALL_PROP_ENGINE_SURFACE_SCHEMA_INVALID")
    return payload


def _repo_relative(surface_path: Path, declared: str) -> Path:
    path = Path(str(declared or "").strip())
    if not path.as_posix():
        raise FootballPropSurfaceError("FOOTBALL_PROP_REGISTRY_PATH_REQUIRED")
    if path.is_absolute():
        return path
    sibling = surface_path.parent / path.name
    if sibling.exists():
        return sibling
    if surface_path.parent.name == "config":
        return surface_path.parent.parent / path
    return path


def _freeze_state(surface_path: Path, spec: Mapping[str, Any], sport: str) -> tuple[str, str | None]:
    registry_path = _repo_relative(surface_path, str(spec.get("freeze_registry") or ""))
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise FootballPropSurfaceError(f"FOOTBALL_PROP_FREEZE_REGISTRY_UNREADABLE:{sport}") from exc
    if not isinstance(registry, Mapping) or str(registry.get("sport") or "").upper() != sport:
        raise FootballPropSurfaceError(f"FOOTBALL_PROP_FREEZE_REGISTRY_INVALID:{sport}")
    status = str(registry.get("status") or "").upper()
    if status == "FROZEN":
        artifact_sha = str(registry.get("artifact_sha256") or "").strip().lower()
        if len(artifact_sha) != 64 or any(ch not in "0123456789abcdef" for ch in artifact_sha):
            raise FootballPropSurfaceError(f"FOOTBALL_PROP_FROZEN_ARTIFACT_SHA_INVALID:{sport}")
        return "ARTIFACT_FROZEN_EVIDENCE_GATED", artifact_sha
    return "MODEL_ARTIFACT_BLOCKED", None


def require_executable_prop_surface(sport: str, *, path: str | Path = DEFAULT_PROP_SURFACE) -> Mapping[str, Any]:
    surface_path = Path(path)
    payload = load_prop_surface(surface_path)
    if payload.get("library_entrypoint") != EXPECTED_LIBRARY_ENTRYPOINT:
        raise FootballPropSurfaceError("FOOTBALL_PROP_LIBRARY_ENTRYPOINT_NOT_EVIDENCE_BOUND")
    module_name, attr = EXPECTED_LIBRARY_ENTRYPOINT.split(":", 1)
    if not hasattr(importlib.import_module(module_name), attr):
        raise FootballPropSurfaceError("FOOTBALL_PROP_LIBRARY_ENTRYPOINT_UNRESOLVABLE")
    resolved = str(sport or "").strip().upper()
    sports = payload.get("sports")
    if not isinstance(sports, Mapping) or not isinstance(sports.get(resolved), Mapping):
        raise FootballPropSurfaceError(f"FOOTBALL_PROP_ENGINE_SURFACE_SPORT_MISSING:{resolved}")
    spec = sports[resolved]
    if spec.get("engine_state") != "IMPLEMENTED_FAIL_CLOSED":
        raise FootballPropSurfaceError(f"FOOTBALL_PROP_ENGINE_NOT_IMPLEMENTED:{resolved}")
    if spec.get("promotion_state") != "AUTOMATIC_TRUTH_GATE_GATED":
        raise FootballPropSurfaceError(f"FOOTBALL_PROP_PROMOTION_STATE_INVALID:{resolved}")
    if spec.get("readiness_state") != "REGISTRY_DERIVED":
        raise FootballPropSurfaceError(f"FOOTBALL_PROP_READINESS_MUST_BE_REGISTRY_DERIVED:{resolved}")
    for field, error in (("freeze_registry","FREEZE_REGISTRY_UNBOUND"),("evidence_registry","EVIDENCE_REGISTRY_UNBOUND"),("certification_registry","CERTIFICATION_REGISTRY_UNBOUND")):
        if not str(spec.get(field) or "").strip():
            raise FootballPropSurfaceError(f"FOOTBALL_PROP_{error}:{resolved}")
    declared = payload.get("implemented_provider_markets")
    if not isinstance(declared, Mapping) or not declared:
        raise FootballPropSurfaceError("FOOTBALL_PROP_IMPLEMENTED_MARKETS_REQUIRED")
    provider_keys=set()
    for family, values in declared.items():
        if not isinstance(values, list) or not values:
            raise FootballPropSurfaceError(f"FOOTBALL_PROP_IMPLEMENTED_MARKET_FAMILY_INVALID:{family}")
        provider_keys.update(str(value) for value in values)
    if provider_keys != set(PROVIDER_MARKETS):
        raise FootballPropSurfaceError("FOOTBALL_PROP_PROVIDER_MARKET_SURFACE_MISMATCH")
    governance=payload.get("governance")
    required_true=("official_bets_allowed_when_all_gates_pass","requires_frozen_artifact","requires_pregame_feature_snapshot","paired_price_required_for_devig","one_sided_offer_ev_allowed_with_model_p","requires_pregame_quote","requires_quote_ttl","requires_forward_evidence_for_promotion","requires_artifact_bound_certification","requires_frozen_edge_floor_before_promotable_inference","evidence_resolution_time_enforced")
    if not isinstance(governance, Mapping) or any(governance.get(k) is not True for k in required_true):
        raise FootballPropSurfaceError("FOOTBALL_PROP_GOVERNANCE_CONTRACT_INVALID")
    required_false=("manual_eligible_toggle_required","market_prices_can_create_model_p","hit_rates_can_create_model_p","capper_or_consensus_can_create_model_p","one_sided_market_can_create_model_p","one_sided_market_can_create_fair_market_p")
    if any(governance.get(k) is not False for k in required_false):
        raise FootballPropSurfaceError("FOOTBALL_PROP_MODEL_P_GOVERNANCE_INVALID")
    runtime_state, artifact_sha = _freeze_state(surface_path, spec, resolved)
    return {**dict(spec), "runtime_state": runtime_state, "frozen_artifact_sha256": artifact_sha}
