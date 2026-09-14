"""Floor-aware MLB promotion readiness inventory.

This module is deliberately diagnostic. It cannot freeze floors, promote markets,
change deployment eligibility, create Model_P, or grant OFFICIAL status. It joins
the existing finish-line/six-gate view to the production edge-floor contract so a
market cannot appear promotion-ready while its required frozen floor is absent.
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
        # MLB market names overlap NFL/CFB aliases. Never ask the v3 resolver to
        # infer sport here: an ambiguous shared alias is a false readiness block.
        floor = require_frozen_edge_floor(market=market, sport="MLB", config=config)
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


def _predeployment_complete(acceptance_row: Mapping[str, Any]) -> bool:
    """Return readiness immediately before the deployment eligibility switch.

    ``acceptance_complete`` intentionally includes deployment eligibility, so it
    cannot answer the transition question "is this market ready to be made
    eligible?". This predicate uses the same canonical acceptance state and
    removes only that final deployment flag. It grants no authority by itself.
    """
    state = acceptance_row.get("current_state")
    if not isinstance(state, Mapping):
        return False
    return bool(
        state.get("runtime_engine") is True
        and state.get("registered") is True
        and str(state.get("behavioral_status", "")).upper() == "KEEP_MEASURED"
        and str(state.get("feature_realization_status", "")).upper() == "COMPLETE"
        and not list(state.get("validation_missing") or [])
    )


def build_mlb_promotion_readiness(
    *,
    edge_floor_path: str | Path = DEFAULT_EDGE_FLOOR_CONFIG,
    **finish_line_kwargs: Any,
) -> dict[str, Any]:
    """Return an honesty-first promotion inventory for every canonical MLB market.

    ``acceptance_complete`` remains the final deployed acceptance state. The
    separate ``predeployment_complete`` state answers whether runtime, registry,
    behavioral, feature-realization, and all six validation gates are complete
    before eligibility is switched on. A frozen edge floor is an additional
    production prerequisite. ``official_ready`` requires all of those conditions
    plus deployment eligibility; this function never changes that flag.
    """
    finish = build_mlb_finish_line(**finish_line_kwargs)
    config = load_edge_floor_config(str(edge_floor_path))

    acceptance_kwargs: dict[str, Any] = {}
    for key in ("deployments_path", "behavioral_path", "validation_path"):
        if key in finish_line_kwargs:
            acceptance_kwargs[key] = finish_line_kwargs[key]
    acceptance = build_acceptance_matrix(**acceptance_kwargs)
    acceptance_rows = {str(row["market"]): row for row in acceptance["markets"]}

    rows: list[dict[str, Any]] = []
    for raw in finish["markets"]:
        row = dict(raw)
        market = str(row["market"])
        floor = _floor_readiness(market=market, config=config)
        acceptance_row = acceptance_rows.get(market, {})
        predeployment_complete = _predeployment_complete(acceptance_row)
        six_gate_complete = not list(row.get("validation_missing") or [])
        deployment_eligible = row.get("deployment_eligible") is True
        floor_frozen = floor["frozen"] is True

        blockers = list(row.get("blockers") or [])
        if not floor_frozen and "EDGE_FLOOR_NOT_FROZEN" not in blockers:
            blockers.append("EDGE_FLOOR_NOT_FROZEN")

        promotion_prerequisites_complete = bool(predeployment_complete and floor_frozen)
        official_ready = bool(promotion_prerequisites_complete and deployment_eligible)
        if official_ready and "EDGE_FLOOR_NOT_FROZEN" in blockers:
            raise RuntimeError(f"MLB_PROMOTION_READINESS_INVARIANT_BROKEN:{market}")

        row.update(
            {
                "edge_floor": floor,
                "six_gate_complete": six_gate_complete,
                "predeployment_complete": predeployment_complete,
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
        "six_gate_complete_count": sum(bool(r["six_gate_complete"]) for r in rows),
        "predeployment_complete_count": sum(bool(r["predeployment_complete"]) for r in rows),
        "frozen_edge_floor_count": sum(bool(r["edge_floor"]["frozen"]) for r in rows),
        "promotion_prerequisites_complete_count": sum(bool(r["promotion_prerequisites_complete"]) for r in rows),
        "deployment_eligible_count": sum(bool(r["deployment_eligible"]) for r in rows),
        "official_ready_count": sum(bool(r["official_ready"]) for r in rows),
        "markets": rows,
    }
