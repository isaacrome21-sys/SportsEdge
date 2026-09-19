"""Fail-closed reconstructed CFB selection readiness."""
# Venue-skip acquire PRs must touch this file so the required CFB readiness check runs.
from __future__ import annotations

from typing import Any, Mapping

CFB_SELECTION_READINESS_VERSION = "CFB_SELECTION_READINESS_V1"


def audit_cfb_selection_readiness(
    *,
    prereg: Mapping[str, Any] | None = None,
    acquisition: Mapping[str, Any] | None = None,
    bundle: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    blockers: list[str] = []
    prereg = prereg or {}
    acquisition = acquisition or {}
    bundle = bundle or {}
    if prereg.get("status") not in {"READY_FOR_FIRST_EVALUATION", "READY"}:
        blockers.append("PREREGISTRATION_NOT_READY")
    if acquisition.get("status") not in {"READY_FOR_HISTORICAL_REPLAY", "VERIFIED_BEFORE_FIRST_REPLAY_CALL"}:
        blockers.append("RECONSTRUCTED_ACQUISITION_NOT_READY")
    if not bundle:
        blockers.append("SELECTION_BUNDLE_MISSING")
    ready = not blockers
    return {
        "schema": CFB_SELECTION_READINESS_VERSION,
        "first_evaluation_allowed": ready,
        "reconstructed_acquisition_ready": "RECONSTRUCTED_ACQUISITION_NOT_READY" not in blockers,
        "reconstructed_selection_bundle_ready": "SELECTION_BUNDLE_MISSING" not in blockers,
        "blockers": blockers,
        "attempt_consumed": False,
        "model_p_created": False,
        "official_authority": False,
    }
