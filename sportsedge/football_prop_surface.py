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


def require_executable_prop_surface(
    sport: str, *, path: str | Path = DEFAULT_PROP_SURFACE
) -> Mapping[str, Any]:
    payload = load_prop_surface(path)
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
    if spec.get("promotion_state") != "BLOCKED_EVIDENCE_REQUIRED":
        raise FootballPropSurfaceError(f"FOOTBALL_PROP_PROMOTION_STATE_INVALID:{resolved}")
    freeze_registry = str(spec.get("freeze_registry") or "").strip()
    if not freeze_registry:
        raise FootballPropSurfaceError(f"FOOTBALL_PROP_FREEZE_REGISTRY_UNBOUND:{resolved}")
    evidence_registry = str(spec.get("evidence_registry") or "").strip()
    if not evidence_registry:
        raise FootballPropSurfaceError(f"FOOTBALL_PROP_EVIDENCE_REGISTRY_UNBOUND:{resolved}")

    declared = payload.get("implemented_provider_markets")
    if not isinstance(declared, Mapping) or not declared:
        raise FootballPropSurfaceError("FOOTBALL_PROP_IMPLEMENTED_MARKETS_REQUIRED")
    provider_keys: set[str] = set()
    for family, values in declared.items():
        if not isinstance(values, list) or not values:
            raise FootballPropSurfaceError(f"FOOTBALL_PROP_IMPLEMENTED_MARKET_FAMILY_INVALID:{family}")
        provider_keys.update(str(value) for value in values)
    if provider_keys != set(PROVIDER_MARKETS):
        raise FootballPropSurfaceError("FOOTBALL_PROP_PROVIDER_MARKET_SURFACE_MISMATCH")

    governance = payload.get("governance")
    required_true = (
        "requires_frozen_artifact", "requires_pregame_feature_snapshot",
        "requires_paired_price_for_market_economics", "requires_pregame_quote",
        "requires_quote_ttl", "requires_forward_evidence_for_promotion",
        "evidence_resolution_time_enforced",
    )
    if not isinstance(governance, Mapping) or any(governance.get(k) is not True for k in required_true):
        raise FootballPropSurfaceError("FOOTBALL_PROP_GOVERNANCE_CONTRACT_INVALID")
    if governance.get("official_bets_allowed") is not False:
        raise FootballPropSurfaceError("FOOTBALL_PROP_OFFICIAL_MUST_REMAIN_DISABLED")
    if governance.get("one_sided_market_can_create_fair_market_p") is not False:
        raise FootballPropSurfaceError("FOOTBALL_PROP_ONE_SIDED_FAIR_PRICE_MUST_REMAIN_DISABLED")
    return spec
