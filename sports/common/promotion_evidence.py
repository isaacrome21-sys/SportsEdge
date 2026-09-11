"""Executable PROMOTION_EVIDENCE_POLICY_V2 evaluator.

The module is deliberately small and deterministic. It does not create Model_P,
prices, closes, or evidence. It only evaluates already-captured forward evidence
against the active frozen policy.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import NormalDist
from typing import Iterable, Mapping, Sequence


STATES = {"PAPER", "PROBATION", "OFFICIAL", "BLOCKED"}

_T975 = {
    1: 12.7062, 2: 4.3027, 3: 3.1824, 4: 2.7764, 5: 2.5706,
    6: 2.4469, 7: 2.3646, 8: 2.3060, 9: 2.2622, 10: 2.2281,
    11: 2.2010, 12: 2.1788, 13: 2.1604, 14: 2.1448, 15: 2.1314,
    16: 2.1199, 17: 2.1098, 18: 2.1009, 19: 2.0930, 20: 2.0860,
    21: 2.0796, 22: 2.0739, 23: 2.0687, 24: 2.0639, 25: 2.0595,
    26: 2.0555, 27: 2.0518, 28: 2.0484, 29: 2.0452, 30: 2.0423,
}


@dataclass(frozen=True)
class ClusteredCI:
    mean: float
    standard_error: float
    lower: float
    upper: float
    clusters: int
    df: int
    method: str = "CR1_CLUSTER_BY_SLATE_DATE/STUDENT_T_G_MINUS_1"


def _t975(df: int) -> float:
    if df < 1:
        raise ValueError("STUDENT_T_REQUIRES_POSITIVE_DF")
    if df in _T975:
        return _T975[df]
    z = NormalDist().inv_cdf(0.975)
    d = float(df)
    return z + (z**3 + z) / (4*d) + (5*z**5 + 16*z**3 + 3*z) / (96*d*d)


def clustered_mean_ci(values: Sequence[float], clusters: Sequence[str]) -> ClusteredCI:
    """CR1 CI for an intercept-only mean, clustered by slate date."""
    if len(values) != len(clusters) or not values:
        raise ValueError("CLV_VALUES_AND_CLUSTERS_REQUIRED")
    vals = [float(v) for v in values]
    labels = [str(c) for c in clusters]
    unique = sorted(set(labels))
    g = len(unique)
    if g < 2:
        raise ValueError("AT_LEAST_TWO_CLUSTERS_REQUIRED")
    n = len(vals)
    mean = sum(vals) / n
    scores = {}
    for value, cluster in zip(vals, labels):
        scores[cluster] = scores.get(cluster, 0.0) + (value - mean)
    variance = (g / (g - 1.0)) * sum(s*s for s in scores.values()) / (n*n)
    se = sqrt(max(0.0, variance))
    df = g - 1
    critical = _t975(df)
    return ClusteredCI(mean, se, mean - critical*se, mean + critical*se, g, df)


def normalize_state(state: str, policy: Mapping) -> str:
    normalized = policy.get("state_aliases", {}).get(state, state)
    if normalized not in STATES:
        raise ValueError(f"UNKNOWN_PROMOTION_STATE:{state}")
    return normalized


def policy_is_active(policy: Mapping, manifest: Mapping, git_ref: str) -> bool:
    activation = policy.get("activation", {})
    return (
        manifest.get("active_policy_id") == policy.get("policy_id")
        and manifest.get("active_policy_path") == activation.get("policy_path")
        and manifest.get("evidence_ref") == activation.get("evidence_ref")
        and git_ref == activation.get("evidence_ref")
    )


def _warnings_resolved(warnings: Iterable[Mapping], policy: Mapping) -> bool:
    allowed = set(policy["official_warning_signoff"]["allowed_statuses"])
    required = set(policy["official_warning_signoff"]["signed_off_requires"])
    for warning in warnings:
        status = warning.get("status")
        if status not in allowed:
            return False
        if status == "SIGNED_OFF" and not required.issubset(warning):
            return False
    return True


def evaluate_promotion(
    metrics: Mapping,
    *,
    current_state: str,
    prerequisites: Mapping[str, bool],
    warnings: Iterable[Mapping],
    policy: Mapping,
    manifest: Mapping,
    git_ref: str,
) -> dict:
    """Evaluate one lane at the frozen V2 checkpoints.

    metrics must summarize evidence already bound to one evaluation unit. The
    evaluator never fabricates missing data or creates Model_P.
    """
    state = normalize_state(current_state, policy)

    if not policy_is_active(policy, manifest, git_ref):
        return {"state": "BLOCKED", "decision": "POLICY_NOT_ACTIVE_ON_EVIDENCE_REF"}

    failures = tuple(metrics.get("integrity_failures", ()))
    if failures:
        return {"state": "BLOCKED", "decision": "HARD_INTEGRITY_BLOCK", "reasons": list(failures)}

    drawdown = metrics.get("lane_drawdown_from_peak_units")
    if drawdown is None:
        return {"state": "BLOCKED", "decision": "MISSING_RISK_METRIC"}
    if float(drawdown) >= policy["exposure_caps"]["probation"]["max_lane_drawdown_from_peak_units"]:
        return {"state": "PAPER", "decision": "IMMEDIATE_DRAWDOWN_DEMOTION"}

    count = int(metrics.get("graded_bets", -1))
    checkpoints = policy["checkpoints"]["evaluate_only_at_graded_counts"]
    if count not in checkpoints:
        return {"state": state, "decision": "NO_FIXED_CHECKPOINT", "graded_bets": count}

    required_metric_names = (
        "distinct_games", "slate_clusters", "close_coverage", "mean_clv_pp",
        "clv_ci_lower_pp", "clv_ci_upper_pp", "roi_fraction",
    )
    missing = [name for name in required_metric_names if metrics.get(name) is None]
    if missing:
        return {"state": "BLOCKED", "decision": "MISSING_CHECKPOINT_METRICS", "reasons": missing}

    coverage = float(metrics["close_coverage"])
    roi = float(metrics["roi_fraction"])
    ci_upper = float(metrics["clv_ci_upper_pp"])
    if coverage < policy["forward_capture"]["close"]["min_close_coverage_for_probation_or_official"]:
        return {"state": "PAPER", "decision": "CHECKPOINT_KILL_CLOSE_COVERAGE"}
    if roi < -float(policy["checkpoints"]["checkpoint_50"]["max_roi_loss_fraction"]):
        return {"state": "PAPER", "decision": "CHECKPOINT_KILL_ROI"}
    if ci_upper < 0.0:
        return {"state": "PAPER", "decision": "CHECKPOINT_KILL_NEGATIVE_CLV_INTERVAL"}

    games = int(metrics["distinct_games"])
    clusters = int(metrics["slate_clusters"])
    mean_clv = float(metrics["mean_clv_pp"])
    ci_lower = float(metrics["clv_ci_lower_pp"])

    if count == 50:
        cp = policy["checkpoints"]["checkpoint_50"]
        missing_prereqs = [name for name in cp["required_before_entry"] if not prerequisites.get(name, False)]
        if missing_prereqs:
            return {"state": "PAPER", "decision": "PROBATION_PREREQUISITES_MISSING", "reasons": missing_prereqs}
        if games < cp["min_distinct_games"] or clusters < cp["min_slate_clusters"]:
            return {"state": "PAPER", "decision": "PROBATION_INDEPENDENCE_DEPTH_INSUFFICIENT"}
        if mean_clv < cp["min_mean_clv_pp"]:
            return {"state": "PAPER", "decision": "PROBATION_MEAN_CLV_NEGATIVE"}
        return {"state": "PROBATION", "decision": "ENTER_PROBATION"}

    if count == 100:
        if state != "PROBATION":
            return {"state": state, "decision": "PROBATION_ENTRY_CHECKPOINT_MISSED"}
        cp = policy["checkpoints"]["checkpoint_100"]
        if games < cp["min_distinct_games"] or clusters < cp["min_slate_clusters"]:
            return {"state": "PAPER", "decision": "CHECKPOINT_100_DEPTH_INSUFFICIENT"}
        return {"state": "PROBATION", "decision": "CONTINUE_PROBATION"}

    cp = policy["checkpoints"]["checkpoint_150"]
    if state != "PROBATION":
        return {"state": state, "decision": "OFFICIAL_REQUIRES_PROBATION"}
    if games < cp["min_distinct_games"] or clusters < cp["min_slate_clusters"]:
        return {"state": "PROBATION", "decision": "OFFICIAL_DEPTH_INSUFFICIENT"}
    if ci_lower <= cp["clv_ci_lower_pp_must_be_above"]:
        return {"state": "PROBATION", "decision": "OFFICIAL_CLV_LOWER_BOUND_NOT_POSITIVE"}
    if not _warnings_resolved(warnings, policy):
        return {"state": "PROBATION", "decision": "OFFICIAL_WARNINGS_UNRESOLVED"}
    return {"state": "OFFICIAL", "decision": "PROMOTE_OFFICIAL"}
