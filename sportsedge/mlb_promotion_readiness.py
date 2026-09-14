"""Floor-aware MLB promotion readiness inventory.

This module is deliberately diagnostic. It cannot freeze floors, promote markets,
change deployment eligibility, create Model_P, or grant OFFICIAL status. It joins
the existing finish-line view to the production edge-floor contract so a market
can prove its pre-eligibility prerequisites without requiring eligibility first.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .edge_floors import (
    DEFAULT_EDGE_FLOOR_CONFIG,
    EdgeFloorError,
    load_edge_floor_config,
    require_frozen_edge_floor,
)
from .mlb_acceptance_matrix import build_acceptance_matrix
from .mlb_finish_line import build_mlb_finish_line


def _floor_readiness(*, market: str, config: Mapping[str, Any]) -> dict[str, Any]:
    try:
        floor = require_frozen_edge_floor(market=market, config=config)
    except EdgeFloorError as exc:
        return {
            "frozen": False,
            "value_probability_points": None,
            "method_version": None,
            "evidence_sha256": None,
            "blocker": str(exc),
        }
    return {
        "frozen": True,
        "value_probability_points": str(floor.value_probability_points),
        "method_version": floor.method_version,
        "evidence_sha256": floor.evidence_sha256,
        "blocker": None,
    }


def _pre_eligibility_acceptance_complete(current_state: Mapping[str, Any]) -> bool:
    """Return whether acceptance prerequisites are complete before eligibility.

    Deployment eligibility is a promotion decision, not evidence. Requiring it in
    this predicate would make the readiness audit circular: a market could never
    prove it was ready for the eligibility flip until after the flip happened.
    """
    return bool(
        current_state.get("runtime_engine") is True
        and current_state.get("registered") is True
        and str(current_state.get("behavioral_status") or "").upper() == "KEEP_MEASURED"
        and str(current_state.get("feature_realization_status") or "").upper() == "COMPLETE"
        and not list(current_state.get("validation_missing") or [])
    )


def build_mlb_promotion_readiness(
    *,
    edge_floor_path: str | Path = DEFAULT_EDGE_FLOOR_CONFIG,
    **finish_line_kwargs: Any,
) -> dict[str, Any]:
    """Return an honesty-first promotion inventory for every canonical MLB market.

    ``pre_eligibility_acceptance_complete`` proves runtime, registration,
    behavioral measurement, feature realization, and validation evidence without
    consulting the deployment eligibility flag. A frozen edge floor is an
    additional production prerequisite. ``official_ready`` is deliberately not a
    second promotion engine: it requires both the persisted deployment eligibility
    flag and the canonical acceptance matrix to already be complete. This function
    never changes either state.
    """
    finish = build_mlb_finish_line(**finish_line_kwargs)
    acceptance_kwargs = {
        key: finish_line_kwargs[key]
        for key in ("deployments_path", "behavioral_path", "validation_path")
        if key in finish_line_kwargs
    }
    acceptance = build_acceptance_matrix(**acceptance_kwargs)
    acceptance_by_market = {
        str(row["market"]): dict(row) for row in acceptance["markets"]
    }
    config = load_edge_floor_config(str(edge_floor_path))

    finish_markets = {str(row["market"]) for row in finish["markets"]}
    if set(acceptance_by_market) != finish_markets:
        raise RuntimeError("MLB_PROMOTION_READINESS_ACCEPTANCE_CATALOG_MISMATCH")

    rows: list[dict[str, Any]] = []
    for raw in finish["markets"]:
        row = dict(raw)
        market = str(row["market"])
        floor = _floor_readiness(market=market, config=config)
        acceptance_state = dict(acceptance_by_market[market]["current_state"])
        pre_eligibility_complete = _pre_eligibility_acceptance_complete(acceptance_state)
        deployment_eligible = row.get("deployment_eligible") is True
        canonical_acceptance_complete = row.get("acceptance_complete") is True
        floor_frozen = floor["frozen"] is True

        blockers = list(row.get("blockers") or [])
        if not pre_eligibility_complete and "PRE_ELIGIBILITY_ACCEPTANCE_INCOMPLETE" not in blockers:
            blockers.append("PRE_ELIGIBILITY_ACCEPTANCE_INCOMPLETE")
        if not floor_frozen and "EDGE_FLOOR_NOT_FROZEN" not in blockers:
            blockers.append("EDGE_FLOOR_NOT_FROZEN")
        if deployment_eligible and not canonical_acceptance_complete and "CANONICAL_ACCEPTANCE_INCOMPLETE" not in blockers:
            blockers.append("CANONICAL_ACCEPTANCE_INCOMPLETE")

        promotion_prerequisites_complete = bool(pre_eligibility_complete and floor_frozen)
        official_ready = bool(
            promotion_prerequisites_complete
            and deployment_eligible
            and canonical_acceptance_complete
        )
        if official_ready and (
            "EDGE_FLOOR_NOT_FROZEN" in blockers
            or "PRE_ELIGIBILITY_ACCEPTANCE_INCOMPLETE" in blockers
            or "CANONICAL_ACCEPTANCE_INCOMPLETE" in blockers
        ):
            raise RuntimeError(f"MLB_PROMOTION_READINESS_INVARIANT_BROKEN:{market}")

        row.update(
            {
                "pre_eligibility_acceptance_complete": pre_eligibility_complete,
                "edge_floor": floor,
                "promotion_prerequisites_complete": promotion_prerequisites_complete,
                "official_ready": official_ready,
                "promotion_blockers": blockers,
            }
        )
        rows.append(row)

    return {
        "schema_version": 2,
        "authority": {
            "diagnostic_only": True,
            "model_p_authority": False,
            "promotion_authority": False,
            "eligibility_authority": False,
            "official_authority": False,
            "floor_freeze_authority": False,
        },
        "market_count": len(rows),
        "six_gate_complete_count": sum(bool(r["pre_eligibility_acceptance_complete"]) for r in rows),
        "pre_eligibility_acceptance_complete_count": sum(
            bool(r["pre_eligibility_acceptance_complete"]) for r in rows
        ),
        "frozen_edge_floor_count": sum(bool(r["edge_floor"]["frozen"]) for r in rows),
        "promotion_prerequisites_complete_count": sum(bool(r["promotion_prerequisites_complete"]) for r in rows),
        "deployment_eligible_count": sum(bool(r["deployment_eligible"]) for r in rows),
        "official_ready_count": sum(bool(r["official_ready"]) for r in rows),
        "markets": rows,
    }
