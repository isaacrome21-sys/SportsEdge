"""Production readiness wrapper for football player-prop Model_P rows."""
from __future__ import annotations

from typing import Any, Mapping

from sportsedge.football_prop_evidence import assess_market_evidence, load_evidence_registry
from sportsedge.football_prop_extended_run_machine import run_football_extended_props


def run_football_props_ready(
    *,
    evidence_registry: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Run the canonical extended prop model, then resolve evidence dependencies.

    This wrapper is the production/library entry point. Passing a registry is
    useful for deterministic tests; production callers omit it and load the
    checked-in sport registry. Evidence can only add blockers here. It never
    creates Model_P and never promotes a candidate.
    """
    report = run_football_extended_props(**kwargs)
    sport = str(report["sport"])
    registry = dict(evidence_registry) if evidence_registry is not None else load_evidence_registry(sport)
    ready_rows = 0
    for row in report["results"]:
        assessment = assess_market_evidence(
            sport=sport,
            provider_market=row["provider_market"],
            model_artifact_sha256=row["model_artifact_sha256"],
            registry=registry,
        )
        row["evidence_ready"] = assessment["ready"]
        row["evidence_required_groups"] = assessment["required_groups"]
        row["evidence_passed_groups"] = assessment["passed_groups"]
        row["evidence_missing_groups"] = assessment["missing_groups"]
        row["evidence_blocked_groups"] = assessment["blocked_groups"]
        row["evidence_blockers"] = assessment["blockers"]
        if assessment["ready"]:
            ready_rows += 1
        else:
            row["reason"] = assessment["blockers"][0]
        # Evidence readiness alone is not authority to promote. Frozen floors,
        # calibration/CLV policy and deployment governance remain downstream.
        row["bet_status"] = "BLOCKED"
        row["official_eligible"] = False

    report["summary"]["evidence_ready_rows"] = ready_rows
    report["summary"]["evidence_blocked_rows"] = len(report["results"]) - ready_rows
    report["summary"]["official_bets"] = 0
    report["evidence_resolution"] = {
        "schema_version": registry.get("schema_version"),
        "sport": sport,
        "resolution_time_enforced": True,
        "registry_override_used": evidence_registry is not None,
        "can_create_model_p": False,
        "can_promote": False,
    }
    return report
