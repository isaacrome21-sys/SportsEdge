"""Fail-closed governance for the separately preregistered CFB altitude challenger.

No fitting or scoring occurs here. The verifier freezes the search contract and
byte-binds any future static venue-elevation snapshot before evaluation.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping

POLICY_PATH = "config/cfb_altitude_challenger_policy_v1.json"
EXPECTED_SOURCE_SCHEMA_COMMIT = "06dbcb5a7977470c3b6296f1f18c9df64676876f"
EXPECTED_CANDIDATES = (
    "altitude_linear_capped_v1",
    "altitude_bins_v1",
    "altitude_short_rest_interaction_v1",
)
EXPECTED_CANDIDATE_SPECS = (
    {
        "id": "altitude_linear_capped_v1",
        "attempt_number": 1,
        "formula": "min(altitude_delta_ft, 6000) / 1000",
        "fixed_constants": {"cap_ft": 6000, "scale_ft": 1000},
    },
    {
        "id": "altitude_bins_v1",
        "attempt_number": 2,
        "formula": "one-hot bins of altitude_delta_ft using fixed cut points",
        "fixed_constants": {
            "cut_points_ft": [1000, 3000],
            "bins": ["[0,1000)", "[1000,3000)", "[3000,+inf)"],
        },
    },
    {
        "id": "altitude_short_rest_interaction_v1",
        "attempt_number": 3,
        "formula": "(min(altitude_delta_ft, 6000) / 1000) * I(away_rest_days <= 6)",
        "fixed_constants": {"cap_ft": 6000, "scale_ft": 1000, "short_rest_days_max": 6},
        "rest_contract": "away_rest_days must be computed only from games completed before target kickoff; missing prior-game evidence fails closed.",
    },
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


class CFBAltitudePreregError(ValueError):
    pass


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


def _is_git_sha(value: object) -> bool:
    return isinstance(value, str) and _GIT_SHA.fullmatch(value.lower()) is not None


def audit_altitude_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    if policy.get("schema") != "CFB_ALTITUDE_CHALLENGER_POLICY_V1":
        blockers.append("POLICY_SCHEMA_MISMATCH")
    if policy.get("status") != "FROZEN_BEFORE_CANDIDATE_EVALUATION":
        blockers.append("POLICY_NOT_FROZEN_BEFORE_EVALUATION")

    g = policy.get("governance") if isinstance(policy.get("governance"), Mapping) else {}
    if not g:
        blockers.append("GOVERNANCE_MISSING")
    checks = (
        (g.get("separate_from_cfb_model_selection_policy_v1") is True, "FROZEN_V1_SEARCH_MUST_REMAIN_SEPARATE"),
        (g.get("candidate_attempt_budget") == 3, "ATTEMPT_BUDGET_MUST_EQUAL_THREE"),
        (g.get("attempts_consumed") == 0, "FIRST_GATE_REQUIRES_ZERO_ATTEMPTS_CONSUMED"),
        (g.get("market_data_allowed") is False, "MARKET_INPUTS_MUST_BE_DISABLED"),
        (g.get("season_2026_allowed_for_fit_tune_or_selection") is False, "SEASON_2026_MUST_BE_EXCLUDED"),
        (g.get("selection_mode_until_closing_line_gate_clears") == "GAME_SCORE_OUTCOMES_ONLY", "SELECTION_MUST_BE_GAME_SCORE_OUTCOMES_ONLY"),
    )
    blockers.extend(code for ok, code in checks if not ok)

    feature = policy.get("feature_contract") if isinstance(policy.get("feature_contract"), Mapping) else {}
    if not feature:
        blockers.append("FEATURE_CONTRACT_MISSING")
    if feature.get("base_definition") != "altitude_delta_ft = max(game_venue_elevation_ft - away_team_home_venue_elevation_ft, 0)":
        blockers.append("ALTITUDE_BASE_DEFINITION_MISMATCH")
    if feature.get("missing_or_unresolved_venue_rule") != "FAIL_CLOSED":
        blockers.append("UNRESOLVED_VENUE_MUST_FAIL_CLOSED")
    rows = feature.get("candidates") if isinstance(feature.get("candidates"), list) else []
    candidate_ids = tuple(row.get("id") for row in rows if isinstance(row, Mapping))
    if candidate_ids != EXPECTED_CANDIDATES:
        blockers.append("CANDIDATE_SET_OR_ORDER_MISMATCH")
    if rows != list(EXPECTED_CANDIDATE_SPECS):
        blockers.append("CANDIDATE_SPEC_MUTATED")

    source = policy.get("source_contract") if isinstance(policy.get("source_contract"), Mapping) else {}
    if not source:
        blockers.append("SOURCE_CONTRACT_MISSING")
    if source.get("provider") != "CollegeFootballData":
        blockers.append("SOURCE_PROVIDER_MISMATCH")
    if source.get("license_cost_requirement") != "FREE_SOURCE_ONLY":
        blockers.append("SOURCE_MUST_BE_FREE")
    source_sha = source.get("schema_commit_sha")
    if source_sha != EXPECTED_SOURCE_SCHEMA_COMMIT:
        blockers.append("SOURCE_SCHEMA_COMMIT_MISMATCH")
    if not _is_git_sha(source_sha):
        blockers.append("SOURCE_SCHEMA_COMMIT_SHA_INVALID")
    if source.get("missing_elevation_policy") != "FAIL_CLOSED_NO_IMPUTATION":
        blockers.append("MISSING_ELEVATION_MUST_FAIL_CLOSED")
    if source.get("snapshot_required_before_any_fit") is not True:
        blockers.append("SNAPSHOT_MUST_PRECEDE_FIT")
    snapshot = source.get("snapshot_contract") if isinstance(source.get("snapshot_contract"), Mapping) else {}
    if not snapshot:
        blockers.append("SNAPSHOT_CONTRACT_MISSING")
    if snapshot.get("required_manifest_fields") != [
        "source_provider", "source_schema_commit_sha", "retrieved_at_utc", "record_count", "content_sha256"
    ]:
        blockers.append("SNAPSHOT_MANIFEST_FIELDS_MISMATCH")
    if snapshot.get("content_sha256_algorithm") != "SHA-256":
        blockers.append("SNAPSHOT_HASH_ALGORITHM_MISMATCH")
    if snapshot.get("manifest_must_be_bound_before_first_evaluation") is not True:
        blockers.append("SNAPSHOT_MANIFEST_MUST_PRECEDE_EVALUATION")
    if snapshot.get("post_binding_mutation_policy") != "NEW_POLICY_VERSION_REQUIRED":
        blockers.append("SNAPSHOT_MUTATION_POLICY_MISMATCH")

    evaluation = policy.get("evaluation_contract") if isinstance(policy.get("evaluation_contract"), Mapping) else {}
    if not evaluation:
        blockers.append("EVALUATION_CONTRACT_MISSING")
    if evaluation.get("dataset_manifest_required_before_first_fit") is not True:
        blockers.append("DATASET_MANIFEST_MUST_PRECEDE_FIT")
    primary = evaluation.get("primary_metric") if isinstance(evaluation.get("primary_metric"), Mapping) else {}
    if primary.get("name") != "joint_score_rmse":
        blockers.append("PRIMARY_METRIC_MUST_BE_JOINT_SCORE_RMSE")
    if evaluation.get("split_rule") != "WALK_FORWARD_BY_SEASON_NO_RANDOM_FOLDS":
        blockers.append("WALK_FORWARD_SPLIT_REQUIRED")
    if evaluation.get("market_metrics_prohibited_until_issue_1070_clears") != [
        "ats_accuracy", "closing_line_value", "market_edge", "market_ev"
    ]:
        blockers.append("MARKET_METRIC_PROHIBITION_MISMATCH")

    baseline = policy.get("baseline_contract") if isinstance(policy.get("baseline_contract"), Mapping) else {}
    if not baseline:
        blockers.append("BASELINE_CONTRACT_MISSING")
    if baseline.get("targets") != ["final_home_points", "final_away_points"]:
        blockers.append("OUTCOME_TARGETS_MISMATCH")
    if not isinstance(baseline.get("prohibited_inputs"), list) or not baseline.get("prohibited_inputs"):
        blockers.append("PROHIBITED_INPUTS_MISSING")

    return {
        "schema": "CFB_ALTITUDE_PREREG_AUDIT_V1",
        "status": "READY_TO_BIND_SNAPSHOT" if not blockers else "BLOCKED_ALTITUDE_PREREG",
        "blockers": blockers,
        "candidate_attempt_budget": g.get("candidate_attempt_budget"),
        "attempts_consumed": g.get("attempts_consumed"),
        "candidate_ids": list(candidate_ids),
        "fit_performed": False,
        "evaluation_performed": False,
        "attempt_consumed_by_this_audit": False,
        "model_p_created": False,
        "promotion_authority": False,
        "official_authority": False,
    }


def verify_altitude_snapshot(*, policy: Mapping[str, Any], manifest: Mapping[str, Any], snapshot_path: Path) -> dict[str, Any]:
    audit = audit_altitude_policy(policy)
    blockers = list(audit["blockers"])
    source = policy.get("source_contract") if isinstance(policy.get("source_contract"), Mapping) else {}
    if manifest.get("source_provider") != source.get("provider"):
        blockers.append("SNAPSHOT_SOURCE_PROVIDER_MISMATCH")
    if manifest.get("source_schema_commit_sha") != source.get("schema_commit_sha"):
        blockers.append("SNAPSHOT_SCHEMA_COMMIT_MISMATCH")
    if not isinstance(manifest.get("retrieved_at_utc"), str) or not manifest.get("retrieved_at_utc", "").strip():
        blockers.append("SNAPSHOT_RETRIEVED_AT_MISSING")
    count = manifest.get("record_count")
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        blockers.append("SNAPSHOT_RECORD_COUNT_INVALID")
    expected_hash = manifest.get("content_sha256")
    if not _is_sha256(expected_hash):
        blockers.append("SNAPSHOT_SHA256_INVALID")

    path = Path(snapshot_path)
    actual_hash: str | None = None
    if not path.is_file():
        blockers.append("SNAPSHOT_FILE_MISSING")
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
    return audit_altitude_policy(_load_json(Path(root) / POLICY_PATH))


__all__ = [
    "CFBAltitudePreregError",
    "EXPECTED_CANDIDATES",
    "EXPECTED_SOURCE_SCHEMA_COMMIT",
    "POLICY_PATH",
    "audit_altitude_policy",
    "audit_altitude_prereg_from_root",
    "verify_altitude_snapshot",
]
