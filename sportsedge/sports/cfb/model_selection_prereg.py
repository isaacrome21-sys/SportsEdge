"""Fail-closed preregistration gate for CFB model-selection attempts.

This module does not fit or evaluate a model and cannot consume an attempt. It
only verifies that every candidate specification required by the frozen
CFB_MODEL_SELECTION_POLICY_V1 is complete before any evaluation is allowed.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_SPEC_FIELDS = (
    "formula",
    "feature_list",
    "weighting_blending_constants",
    "training_window",
    "hyperparameter_policy",
    "source_contract_identity",
    "code_sha256",
    "config_sha256",
)


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _sha(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value.strip().lower()) is not None


def _candidate_blockers(candidate: Mapping[str, Any], family: str) -> list[str]:
    blockers: list[str] = []
    if candidate.get("family") != family:
        blockers.append("FAMILY_IDENTITY_MISMATCH")
    if candidate.get("status") != "PREREGISTERED_UNEVALUATED":
        blockers.append("STATUS_MUST_BE_PREREGISTERED_UNEVALUATED")
    if not _nonempty_string(candidate.get("formula")):
        blockers.append("FORMULA_MISSING")
    features = candidate.get("feature_list")
    if not isinstance(features, list) or not features or not all(_nonempty_string(x) for x in features):
        blockers.append("FEATURE_LIST_MISSING_OR_EMPTY")
    if not isinstance(candidate.get("weighting_blending_constants"), Mapping):
        blockers.append("WEIGHTING_BLENDING_CONSTANTS_MISSING")
    if not isinstance(candidate.get("training_window"), Mapping) or not candidate.get("training_window"):
        blockers.append("TRAINING_WINDOW_MISSING")
    if not isinstance(candidate.get("hyperparameter_policy"), Mapping) or not candidate.get("hyperparameter_policy"):
        blockers.append("HYPERPARAMETER_POLICY_MISSING")
    if not _nonempty_string(candidate.get("source_contract_identity")):
        blockers.append("SOURCE_CONTRACT_IDENTITY_MISSING")
    if not _sha(candidate.get("code_sha256")):
        blockers.append("CODE_SHA256_MISSING_OR_INVALID")
    if not _sha(candidate.get("config_sha256")):
        blockers.append("CONFIG_SHA256_MISSING_OR_INVALID")
    forbidden = {"selection_metric_value", "rmse", "evaluation_result", "winner", "null_threshold"}
    if any(key in candidate for key in forbidden):
        blockers.append("POST_EVALUATION_FIELD_PRESENT_IN_PREREGISTRATION")
    return blockers


def audit_model_selection_prereg(
    policy: Mapping[str, Any],
    preregistration: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return a deterministic readiness report without fitting or scoring anything."""
    blockers: list[str] = []
    if policy.get("schema") != "CFB_MODEL_SELECTION_POLICY_V1":
        blockers.append("POLICY_SCHEMA_MISMATCH")
    if policy.get("status") != "FROZEN_BEFORE_CANDIDATE_EVALUATION":
        blockers.append("POLICY_NOT_FROZEN_BEFORE_EVALUATION")

    try:
        budget = int(policy.get("candidate_attempt_budget"))
        attempts = int(policy.get("attempts_consumed"))
    except (TypeError, ValueError):
        budget, attempts = -1, -1
        blockers.append("ATTEMPT_ACCOUNTING_INVALID")

    families = policy.get("candidate_families_predeclared")
    if not isinstance(families, list) or not families or not all(_nonempty_string(x) for x in families):
        families = []
        blockers.append("PREDECLARED_FAMILIES_INVALID")
    if budget != len(families):
        blockers.append("ATTEMPT_BUDGET_FAMILY_COUNT_MISMATCH")
    if attempts < 0 or attempts > budget:
        blockers.append("ATTEMPTS_CONSUMED_OUT_OF_RANGE")

    candidate_results: list[dict[str, Any]] = []
    specs = None if preregistration is None else preregistration.get("candidates")
    if not isinstance(specs, Mapping):
        blockers.append("CANDIDATE_PREREGISTRATION_MISSING")
        specs = {}

    extra = sorted(set(str(k) for k in specs) - set(str(x) for x in families))
    if extra:
        blockers.append("UNDECLARED_CANDIDATE_FAMILY_PRESENT")

    for family in families:
        candidate = specs.get(family)
        if not isinstance(candidate, Mapping):
            row_blockers = ["CANDIDATE_SPEC_MISSING"]
        else:
            row_blockers = _candidate_blockers(candidate, family)
        if row_blockers:
            blockers.append(f"CANDIDATE_INCOMPLETE:{family}")
        candidate_results.append({"family": family, "complete": not row_blockers, "blockers": row_blockers})

    ready = not blockers and attempts == 0
    if attempts != 0:
        blockers.append("FIRST_EVALUATION_GATE_REQUIRES_ZERO_ATTEMPTS_CONSUMED")
        ready = False

    return {
        "schema": "CFB_MODEL_SELECTION_PREREG_AUDIT_V1",
        "status": "READY_FOR_FIRST_EVALUATION" if ready else "BLOCKED_PREREG_INCOMPLETE",
        "candidate_attempt_budget": budget,
        "attempts_consumed": attempts,
        "candidate_results": candidate_results,
        "blockers": blockers,
        "attempt_consumed_by_this_audit": False,
        "model_fit_performed": False,
        "model_p_created": False,
        "promotion_authority": False,
        "eligibility_changed": False,
    }


__all__ = ["audit_model_selection_prereg", "REQUIRED_SPEC_FIELDS"]
