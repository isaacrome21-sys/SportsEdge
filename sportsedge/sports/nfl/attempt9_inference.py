"""Frozen prospective CLV inference for NFL attempt-9.

This module implements the separately frozen inference addendum.  It does not
fit a model, inspect a promotion readout, or grant any promotion/deployment
authority.
"""
from __future__ import annotations

from hashlib import sha1
import json
from math import isfinite, sqrt
from pathlib import Path
from statistics import mean, stdev
from typing import Any, Mapping, Sequence

POLICY_PATH = Path(__file__).resolve().parents[3] / "config/nfl_attempt9_prospective_inference_v1.json"
EXPECTED_POLICY_GIT_BLOB_SHA1 = "00fd09af015fe60f18a8d325c2dde3e9c7c123ee"
POLICY_SCHEMA = "SPORTSEDGE_NFL_ATTEMPT9_PROSPECTIVE_INFERENCE_V1"

# Two-sided 95% Student-t critical values (0.975 quantile).  The frozen policy
# requires at least 12 NFL-week clusters, so the supported one-season range
# begins at df=11.  Failing outside the table is safer than silently switching
# to a normal approximation.
_T_975_BY_DF = {
    11: 2.200985160092,
    12: 2.178812829667,
    13: 2.160368656463,
    14: 2.144786687918,
    15: 2.131449545560,
    16: 2.119905299221,
    17: 2.109815577833,
    18: 2.100922040241,
    19: 2.093024054408,
    20: 2.085963447266,
    21: 2.079613844728,
    22: 2.073873067904,
    23: 2.068657610419,
    24: 2.063898561628,
    25: 2.059538552753,
    26: 2.055529438643,
    27: 2.051830516480,
    28: 2.048407141795,
    29: 2.045229642133,
    30: 2.042272456301,
}


class NFLAttempt9InferenceError(ValueError):
    """Raised when the frozen inference contract cannot be proven exactly."""


def _git_blob_sha1(content: bytes) -> str:
    return sha1(f"blob {len(content)}\0".encode("ascii") + content).hexdigest()


def load_frozen_inference_policy() -> dict[str, Any]:
    raw = POLICY_PATH.read_bytes()
    actual = _git_blob_sha1(raw)
    if actual != EXPECTED_POLICY_GIT_BLOB_SHA1:
        raise NFLAttempt9InferenceError(
            f"NFL_A9_INFERENCE_POLICY_BLOB_MISMATCH:expected={EXPECTED_POLICY_GIT_BLOB_SHA1}:actual={actual}"
        )
    try:
        policy = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NFLAttempt9InferenceError("NFL_A9_INFERENCE_POLICY_JSON_INVALID") from exc
    if not isinstance(policy, dict):
        raise NFLAttempt9InferenceError("NFL_A9_INFERENCE_POLICY_SHAPE_INVALID")
    return policy


def validate_inference_policy(
    policy: Mapping[str, Any], *, thresholds: Mapping[str, Any]
) -> None:
    if policy.get("schema") != POLICY_SCHEMA or policy.get("status") != "FROZEN_BEFORE_PROMOTION_READOUT_USE":
        raise NFLAttempt9InferenceError("NFL_A9_INFERENCE_POLICY_IDENTITY_INVALID")
    scope = policy.get("scope") or {}
    if (
        scope.get("sport") != "NFL"
        or scope.get("season") != 2026
        or scope.get("candidate") != "attempt-9"
        or scope.get("role") != "PROSPECTIVE_TRUTH_GATE_INFERENCE_ONLY"
        or scope.get("markets") != ["spread", "total"]
    ):
        raise NFLAttempt9InferenceError("NFL_A9_INFERENCE_POLICY_SCOPE_INVALID")

    uniqueness = policy.get("decision_uniqueness") or {}
    if (
        uniqueness.get("key") != ["game_id", "market", "selection"]
        or uniqueness.get("canonical_rule") != "EARLIEST_VALID_DECISION_AT_UTC_THEN_SHA256"
        or uniqueness.get("later_captures_may_increase_sample_size") is not False
        or uniqueness.get("evidence_availability_may_choose_capture") is not False
        or uniqueness.get("backfill_allowed") is not False
    ):
        raise NFLAttempt9InferenceError("NFL_A9_INFERENCE_UNIQUENESS_POLICY_INVALID")

    inf = policy.get("clv_inference") or {}
    expected = {
        "estimand": "MEAN_CLV_PROBABILITY_POINTS",
        "iid_statistic": "ONE_SAMPLE_T_STAT_ON_ELIGIBLE_DECISION_CLV",
        "cluster_estimator": "CR1_INTERCEPT_ONLY_CLUSTER_ROBUST",
        "cluster_unit": "NFL_WEEK",
        "cluster_df": "G_MINUS_1",
        "cluster_reference_distribution": "STUDENT_T",
        "cluster_reference_quantile": 0.975,
        "cluster_reference_df": "G_MINUS_1",
        "small_sample_correction": "CR1_G_OVER_G_MINUS_1_FOR_INTERCEPT_ONLY_MEAN",
        "nonfinite_statistic_passes": False,
    }
    if any(inf.get(key) != value for key, value in expected.items()):
        raise NFLAttempt9InferenceError("NFL_A9_INFERENCE_METHOD_INVALID")
    if inf.get("cluster_pass_rule") != "CLUSTER_T_STAT_MUST_BE_AT_LEAST_MAX_2_0_AND_T_0_975_G_MINUS_1":
        raise NFLAttempt9InferenceError("NFL_A9_INFERENCE_CLUSTER_PASS_RULE_INVALID")
    if inf.get("combined_pass_rule") != "IID_T_STAT_MUST_BE_AT_LEAST_2_0_AND_CLUSTER_PASS_RULE_MUST_PASS":
        raise NFLAttempt9InferenceError("NFL_A9_INFERENCE_COMBINED_PASS_RULE_INVALID")

    frozen_iid = float(thresholds["minimum_clv_t_stat"])
    frozen_clusters = int(thresholds["minimum_distinct_week_clusters"])
    if float(inf.get("iid_t_stat_floor")) != frozen_iid:
        raise NFLAttempt9InferenceError("NFL_A9_INFERENCE_IID_FLOOR_DRIFT")
    if float(inf.get("cluster_t_stat_floor")) < frozen_iid:
        raise NFLAttempt9InferenceError("NFL_A9_INFERENCE_CLUSTER_FLOOR_RELAXED")
    if int(inf.get("minimum_distinct_clusters")) < frozen_clusters:
        raise NFLAttempt9InferenceError("NFL_A9_INFERENCE_CLUSTER_COUNT_RELAXED")

    coverage = policy.get("coverage") or {}
    if (
        coverage.get("pending_or_missing_evidence_may_disappear_from_denominator") is not False
        or coverage.get("pending_rows_report_separately") is not True
        or coverage.get("complete_canonical_evidence_required_for_gate_pass") is not True
    ):
        raise NFLAttempt9InferenceError("NFL_A9_INFERENCE_COVERAGE_POLICY_INVALID")

    governance = policy.get("governance") or {}
    false_keys = (
        "may_lower_existing_thresholds",
        "may_use_2026_outcomes_to_choose_estimator",
        "may_use_2026_clv_to_choose_estimator",
        "may_change_model_probability",
        "may_change_model_features",
        "may_change_edge_floor",
        "promotion_authority",
        "official_authority",
        "staking_authority",
    )
    if any(governance.get(key) is not False for key in false_keys):
        raise NFLAttempt9InferenceError("NFL_A9_INFERENCE_AUTHORITY_INVALID")

    if dict(policy) != load_frozen_inference_policy():
        raise NFLAttempt9InferenceError("NFL_A9_INFERENCE_POLICY_DRIFT")


def _iid_t(values: Sequence[float]) -> float:
    if len(values) < 2:
        return float("nan")
    sd = stdev(values)
    if sd <= 0:
        return float("nan")
    return mean(values) / (sd / sqrt(len(values)))


def _cluster_t(values: Sequence[float], weeks: Sequence[int]) -> tuple[float, int]:
    if len(values) != len(weeks):
        raise NFLAttempt9InferenceError("NFL_A9_INFERENCE_LENGTH_MISMATCH")
    if len(values) < 2:
        return float("nan"), len(set(weeks))
    groups: dict[int, list[float]] = {}
    for value, week in zip(values, weeks):
        groups.setdefault(int(week), []).append(float(value))
    g = len(groups)
    if g < 2:
        return float("nan"), g
    mu = mean(values)
    cluster_scores = [sum(value - mu for value in group) for group in groups.values()]
    variance = (g / (g - 1.0)) * sum(score * score for score in cluster_scores) / (len(values) ** 2)
    if variance <= 0:
        return float("nan"), g
    return mu / sqrt(variance), g


def student_t_975(df: int) -> float:
    try:
        return _T_975_BY_DF[int(df)]
    except KeyError as exc:
        raise NFLAttempt9InferenceError(f"NFL_A9_INFERENCE_T_REFERENCE_UNSUPPORTED_DF:{df}") from exc


def compute_clv_inference(
    values: Sequence[float],
    weeks: Sequence[int],
    *,
    policy: Mapping[str, Any],
    thresholds: Mapping[str, Any],
) -> dict[str, Any]:
    validate_inference_policy(policy, thresholds=thresholds)
    values = [float(value) for value in values]
    weeks = [int(week) for week in weeks]
    if len(values) != len(weeks):
        raise NFLAttempt9InferenceError("NFL_A9_INFERENCE_LENGTH_MISMATCH")

    inf = policy["clv_inference"]
    n = len(values)
    mu = mean(values) if values else float("nan")
    iid_t = _iid_t(values)
    cluster_t, g = _cluster_t(values, weeks)
    minimum_clusters = int(inf["minimum_distinct_clusters"])
    df = g - 1 if g else 0
    if g >= minimum_clusters:
        t_reference = student_t_975(df)
        cluster_required = max(float(inf["cluster_t_stat_floor"]), t_reference)
    else:
        t_reference = float("inf")
        cluster_required = float("inf")

    iid_pass = n >= 2 and isfinite(iid_t) and iid_t >= float(inf["iid_t_stat_floor"])
    cluster_pass = (
        g >= minimum_clusters
        and isfinite(cluster_t)
        and isfinite(cluster_required)
        and cluster_t >= cluster_required
    )
    return {
        "policy_resolved": True,
        "policy_git_blob_sha1": EXPECTED_POLICY_GIT_BLOB_SHA1,
        "mean_clv": mu,
        "iid_t_stat": iid_t,
        "iid_t_stat_floor": float(inf["iid_t_stat_floor"]),
        "iid_pass": iid_pass,
        "cluster_estimator": inf["cluster_estimator"],
        "cluster_unit": inf["cluster_unit"],
        "cluster_count": g,
        "cluster_df": df,
        "cluster_t_stat": cluster_t,
        "cluster_reference_critical": t_reference,
        "cluster_required_t": cluster_required,
        "cluster_pass": cluster_pass,
        "combined_pass": iid_pass and cluster_pass,
    }


__all__ = [
    "EXPECTED_POLICY_GIT_BLOB_SHA1",
    "NFLAttempt9InferenceError",
    "POLICY_PATH",
    "compute_clv_inference",
    "load_frozen_inference_policy",
    "student_t_975",
    "validate_inference_policy",
]
