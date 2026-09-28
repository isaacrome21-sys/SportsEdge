"""Fail-closed governance for the separately preregistered CFB altitude challenger.

This module does not fit or score a model.  It validates that the altitude search is
separate from the frozen CFB model-selection v1 search and that any future static
venue-elevation snapshot is byte-bound before a candidate can be evaluated.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping


POLICY_PATH = "config/cfb_altitude_challenger_policy_v1.json"
EXPECTED_CANDIDATES = (
    "altitude_linear_capped_v1",
    "altitude_bins_v1",
    "altitude_short_rest_interaction_v1",
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CFBAltitudePreregError(ValueError):
    """Raised when a policy or snapshot manifest cannot be parsed safely."""


def _load_json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CFBAltitudePreregError(f"CFB_ALTITUDE_JSON_INVALID:{path}") from exc
    if not isinstance(value, Mapping):
        raise CFBAltitudePreregError(f"CFB_ALTITUDE_JSON_OBJECT_REQUIRED:{path}")
    return value


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value.lower()) is not None


def audit_altitude_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the frozen search contract without consuming an attempt."""

    blockers: list[str] = []
    if policy.get("schema") != "CFB_ALTITUDE_CHALLENGER_POLICY_V1":
        blockers.append("POLICY_SCHEMA_MISMATCH")
    if policy.get("status") != "FROZEN_BEFORE_CANDIDATE_EVALUATION":
        blockers.append("POLICY_NOT_FROZEN_BEFORE_EVALUATION")

    governance = policy.get("governance")
    if not isinstance(governance, Mapping):
        governance = {}
        blockers.append("GOVERNANCE_MISSING")
    if governance.get("separate_from_cfb_model_selection_policy_v1") is not True:
        blockers.append("FROZEN_V1_SEARCH_MUST_REMAIN_SEPARATE")
    if governance.get("candidate_attempt_budget") != 3:
        blockers.append("ATTEMPT_BUDGET_MUST_EQUAL_THREE")
    if governance.get("attempts_consumed") != 0:
        blockers.append("FIRST_GATE_REQUIRES_ZERO_ATTEMPTS_CONSUMED")
    if governance.get("market_data_allowed") is not False:
        blockers.append("MARKET_INPUTS_MUST_BE_DISABLED")
    if governance.get("season_2026_allowed_for_fit_tune_or_selection") is not False:
        blockers.append("SEASON_2026_MUST_BE_EXCLUDED")
    if governance.get("selection_mode_until_closing_line_gate_clears") != "GAME_SCORE_OUTCOMES_ONLY":
        blockers.append("SELECTION_MUST_BE_GAME_SCORE_OUTCOMES_ONLY")

    feature = policy.get("feature_contract")
    if not isinstance(feature, Mapping):
        feature = {}
        blockers.append("FEATURE_CONTRACT_MISSING")
    rows = feature.get("candidates")
    if not isinstance(rows, list):
        rows = []
        blockers.append("CANDIDATES_MISSING")
    candidate_ids = tuple(row.get("id") for row in rows if isinstance(row, Mapping))
    if candidate_ids != EXPECTED_CANDIDATES:
        blockers.append("CANDIDATE_SET_OR_ORDER_MISMATCH")
    attempt_numbers = tuple(row.get("attempt_number") for row in rows if isinstance(row, Mapping))
    if attempt_numbers != (1, 2, 3):
        blockers.append("CANDIDATE_ATTEMPT_ORDER_MISMATCH")

    source = policy.get("source_contract")
    if not isinstance(source, Mapping):
        source = {}
        blockers.append("SOURCE_CONTRACT_MISSING")
    if source.get("provider") != "CollegeFootballData":
        blockers.append("SOURCE_PROVIDER_MISMATCH")
    if source.get("license_cost_requirement") != "FREE_SOURCE_ONLY":
        blockers.append("SOURCE_MUST_BE_FREE")
    if not _is_sha256(source.get("schema_commit_sha")):
        blockers.append("SOURCE_SCHEMA_COMMIT_SHA_INVALID")
    if source.get("missing_elevation_policy") != "FAIL_CLOSED_NO_IMPUTATION":
        blockers.append("MISSING_ELEVATION_MUST_FAIL_CLOSED")
    if source.get("snapshot_required_before_any_fit") is not True:
        blockers.append("SNAPSHOT_MUST_PRECEDE_FIT")
    snapshot_contract = source.get("snapshot_contract")
    if not isinstance(snapshot_contract, Mapping):
        snapshot_contract = {}
        blockers.append("SNAPSHOT_CONTRACT_MISSING")
    required_manifest = snapshot_contract.get("required_manifest_fields")
    if required_manifest != [
        "source_provider",
        "source_schema_commit_sha",
        "retrieved_at_utc",
        "record_count",
        "content_sha256",
    ]:
        blockers.append("SNAPSHOT_MANIFEST_FIELDS_MISMATCH")
    if snapshot_contract.get("post_binding_mutation_policy") != "NEW_POLICY_VERSION_REQUIRED":
        blockers.append("SNAPSHOT_MUTATION_POLICY_MISMATCH")

    evaluation = policy.get("evaluation_contract")
    if not isinstance(evaluation, Mapping):
        evaluation = {}
        blockers.append("EVALUATION_CONTRACT_MISSING")
    primary = evaluation.get("primary_metric")
    if not isinstance(primary, Mapping) or primary.get("name") != "joint_score_rmse":
        blockers.append("PRIMARY_METRIC_MUST_BE_JOINT_SCORE_RMSE")
    if evaluation.get("split_rule") != "WALK_FORWARD_BY_SEASON_NO_RANDOM_FOLDS":
        blockers.append("WALK_FORWARD_SPLIT_REQUIRED")
    prohibited = evaluation.get("market_metrics_prohibited_until_issue_1070_clears")
    if prohibited != ["ats_accuracy", "closing_line_value", "market_edge", "market_ev"]:
        blockers.append("MARKET_METRIC_PROHIBITION_MISMATCH")

    baseline = policy.get("baseline_contract")
    if not isinstance(baseline, Mapping):
        baseline = {}
        blockers.append("BASELINE_CONTRACT_MISSING")
    if baseline.get("targets") != ["final_home_points", "final_away_points"]:
        blockers.append("OUTCOME_TARGETS_MISMATCH")
    if not baseline.get("prohibited_inputs"):
        blockers.append("PROHIBITED_INPUTS_MISSING")

    return {
        "schema": "CFB_ALTITUDE_PREREG_AUDIT_V1",
        "status": "READY_TO_BIND_SNAPSHOT" if not blockers else "BLOCKED_ALTITUDE_PREREG",
        "blockers": blockers,
        "candidate_attempt_budget": governance.get("candidate_attempt_budget"),
        "attempts_consumed": governance.get("attempts_consumed"),
        "candidate_ids": list(candidate_ids),
        "fit_performed": False,
        "evaluation_performed": False,
        "attempt_consumed_by_this_audit": False,
        "model_p_created": False,
        "promotion_authority": False,
        "official_authority": False,
    }


def verify_altitude_snapshot(
    *,
    policy: Mapping[str, Any],
    manifest: Mapping[str, Any],
    snapshot_path: Path,
) -> dict[str, Any]:
    """Verify a future static-metadata snapshot against its immutable manifest.

    READY means only that policy + bytes are bound. It is not permission to call any
    probability Model_P or to promote a betting output.
    """

    audit = audit_altitude_policy(policy)
    blockers = list(audit["blockers"])
    source = policy.get("source_contract") if isinstance(policy.get("source_contract"), Mapping) else {}

    if manifest.get("source_provider") != source.get("provider"):
        blockers.append("SNAPSHOT_SOURCE_PROVIDER_MISMATCH")
    if manifest.get("source_schema_commit_sha") != source.get("schema_commit_sha"):
        blockers.append("SNAPSHOT_SCHEMA_COMMIT_MISMATCH")
    retrieved = manifest.get("retrieved_at_utc")
    if not isinstance(retrieved, str) or not retrieved.strip():
        blockers.append("SNAPSHOT_RETRIEVED_AT_MISSING")
    count = manifest.get("record_count")
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        blockers.append("SNAPSHOT_RECORD_COUNT_INVALID")
    expected_hash = manifest.get("content_sha256")
    if not _is_sha256(expected_hash):
        blockers.append("SNAPSHOT_SHA256_INVALID")

    path = Path(snapshot_path)
    if not path.is_file():
        blockers.append("SNAPSHOT_FILE_MISSING")
        actual_hash = None
    else:
        actual_hash = sha256(path.read_bytes()).hexdigest()
        if _is_sha256(expected_hash) and actual_hash != expected_hash:
            blockers.append("SNAPSHOT_SHA256_MISMATCH")

    return {
        "schema": "CFB_ALTITUDE_SNAPSHOT_BINDING_V1",
        "status": "SNAPSHOT_BOUND_NO_EVALUATION" if not blockers else "BLOCKED_ALTITUDE_SNAPSHOT",
        "blockers": blockers,
        "content_sha256": actual_hash,
        "fit_performed": False,
        "evaluation_performed": False,
        "attempt_consumed_by_this_verifier": False,
        "model_p_created": False,
        "promotion_authority": False,
        "official_authority": False,
    }


def audit_altitude_prereg_from_root(*, root: Path) -> dict[str, Any]:
    """Load the repository policy and audit it without touching data."""

    policy = _load_json(Path(root) / POLICY_PATH)
    return audit_altitude_policy(policy)


__all__ = [
    "CFBAltitudePreregError",
    "EXPECTED_CANDIDATES",
    "POLICY_PATH",
    "audit_altitude_policy",
    "audit_altitude_prereg_from_root",
    "verify_altitude_snapshot",
]
