"""Fixed-checkpoint evaluator for the governed MLB MONEYLINE V2 lane.

This module reads only completed, already-frozen forward evidence. It cannot create
bets, change Model_P, mutate deployment, stake, or grant OFFICIAL authority.
Promotion Evidence Policy V2 is evaluated only at graded counts 50/100/150.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from math import exp, isfinite, lgamma, log, log1p, sqrt
from pathlib import Path
from typing import Any, Iterable, Mapping

from .mlb_moneyline_forward_lane import (
    MLBMoneylineForwardLaneError,
    load_forward_lane_binding,
    require_record_binding,
)

CHECKPOINT_VERSION = "mlb_moneyline_v2_checkpoint_evaluator_v1"
DEFAULT_POLICY_PATH = Path("config/promotion_evidence_policy_v2.json")
_FIXED_CHECKPOINTS = (50, 100, 150)


class MLBMoneylineV2CheckpointError(ValueError):
    pass


def _finite(value: Any, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise MLBMoneylineV2CheckpointError(f"{field} invalid") from exc
    if not isfinite(out):
        raise MLBMoneylineV2CheckpointError(f"{field} invalid")
    return out


def _utc_date(value: Any) -> str:
    try:
        ts = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise MLBMoneylineV2CheckpointError("event_start_ts invalid") from exc
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise MLBMoneylineV2CheckpointError("event_start_ts timezone required")
    return ts.astimezone(timezone.utc).date().isoformat()


def _load_policy(path: str | Path = DEFAULT_POLICY_PATH) -> dict[str, Any]:
    policy_path = Path(path)
    if not policy_path.is_absolute():
        policy_path = Path(__file__).resolve().parents[1] / policy_path
    try:
        value = json.loads(policy_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise MLBMoneylineV2CheckpointError("promotion policy unreadable") from exc
    if not isinstance(value, dict) or value.get("policy_id") != "PROMOTION_EVIDENCE_POLICY_V2":
        raise MLBMoneylineV2CheckpointError("promotion policy invalid")
    checkpoints = value.get("checkpoints") or {}
    if tuple(checkpoints.get("evaluate_only_at_graded_counts") or ()) != _FIXED_CHECKPOINTS:
        raise MLBMoneylineV2CheckpointError("fixed checkpoint contract mismatch")
    inference = ((value.get("forward_capture") or {}).get("clv_inference") or {})
    if (
        inference.get("confidence_level") != 0.95
        or inference.get("standard_error") != "CR1_CLUSTER_BY_SLATE_DATE"
        or inference.get("cluster_key") != "slate_date"
        or inference.get("reference_distribution") != "STUDENT_T_G_MINUS_1"
        or inference.get("continuous_peeking_for_promotion") is not False
    ):
        raise MLBMoneylineV2CheckpointError("CLV inference contract mismatch")
    return value


def _betacf(a: float, b: float, x: float) -> float:
    # Numerical Recipes continued fraction for the incomplete beta function.
    max_iter = 250
    eps = 3.0e-14
    fpmin = 1.0e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) <= eps:
            return h
    raise MLBMoneylineV2CheckpointError("incomplete beta did not converge")


def _regularized_beta(x: float, a: float, b: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    bt = exp(lgamma(a + b) - lgamma(a) - lgamma(b) + a * log(x) + b * log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def _student_t_cdf(t_value: float, df: int) -> float:
    if df < 1:
        raise MLBMoneylineV2CheckpointError("student-t degrees of freedom invalid")
    if t_value == 0.0:
        return 0.5
    x = df / (df + t_value * t_value)
    ib = _regularized_beta(x, df / 2.0, 0.5)
    return 1.0 - 0.5 * ib if t_value > 0 else 0.5 * ib


def student_t_critical_975(df: int) -> float:
    """Return the two-sided 95% Student-t critical value for ``df``."""
    if df < 1:
        raise MLBMoneylineV2CheckpointError("student-t degrees of freedom invalid")
    lo, hi = 0.0, 64.0
    target = 0.975
    for _ in range(100):
        mid = (lo + hi) / 2.0
        if _student_t_cdf(mid, df) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _cluster_cr1_mean_ci(values: list[float], clusters: list[str]) -> dict[str, Any]:
    if len(values) != len(clusters) or not values:
        raise MLBMoneylineV2CheckpointError("CLV values/clusters invalid")
    grouped: dict[str, list[float]] = {}
    for value, cluster in zip(values, clusters):
        grouped.setdefault(cluster, []).append(value)
    g = len(grouped)
    mean = sum(values) / len(values)
    if g < 2:
        return {
            "mean": mean,
            "standard_error_cr1": None,
            "student_t_df": None,
            "student_t_critical_975": None,
            "ci_95_lower": None,
            "ci_95_upper": None,
        }
    score_sq_sum = 0.0
    for cluster_values in grouped.values():
        score = sum(value - mean for value in cluster_values)
        score_sq_sum += score * score
    variance = (g / (g - 1.0)) * score_sq_sum / (len(values) ** 2)
    se = sqrt(max(0.0, variance))
    df = g - 1
    critical = student_t_critical_975(df)
    return {
        "mean": mean,
        "standard_error_cr1": se,
        "student_t_df": df,
        "student_t_critical_975": critical,
        "ci_95_lower": mean - critical * se,
        "ci_95_upper": mean + critical * se,
    }


def _validate_rows(
    rows: Iterable[Mapping[str, Any]], binding: Mapping[str, Any]
) -> list[dict[str, Any]]:
    validated: list[dict[str, Any]] = []
    seen_games: set[int] = set()
    seen_decisions: set[str] = set()
    artifact: str | None = None
    for source in rows:
        row = dict(source)
        try:
            require_record_binding(row, binding)
        except MLBMoneylineForwardLaneError as exc:
            raise MLBMoneylineV2CheckpointError(str(exc)) from exc
        if row.get("status") != "FORWARD_EVIDENCE_COMPLETE_V2":
            raise MLBMoneylineV2CheckpointError("non-V2 completed row in checkpoint input")
        if row.get("graded_bet") is not True or row.get("evidence_counts") is not True:
            raise MLBMoneylineV2CheckpointError("checkpoint row must be a valid graded bet")
        if row.get("promotion_authority") is not False:
            raise MLBMoneylineV2CheckpointError("checkpoint input authority must remain false")
        try:
            game_pk = int(row.get("game_pk"))
        except (TypeError, ValueError) as exc:
            raise MLBMoneylineV2CheckpointError("game_pk invalid") from exc
        if game_pk in seen_games:
            raise MLBMoneylineV2CheckpointError(f"duplicate game_pk={game_pk}")
        seen_games.add(game_pk)
        decision_sha = str(row.get("decision_record_sha256") or "")
        if len(decision_sha) != 64:
            raise MLBMoneylineV2CheckpointError("decision_record_sha256 invalid")
        if decision_sha in seen_decisions:
            raise MLBMoneylineV2CheckpointError("duplicate decision_record_sha256")
        seen_decisions.add(decision_sha)
        current_artifact = str(row.get("model_artifact_sha256") or "")
        if len(current_artifact) != 64:
            raise MLBMoneylineV2CheckpointError("model_artifact_sha256 invalid")
        if artifact is None:
            artifact = current_artifact
        elif current_artifact != artifact:
            raise MLBMoneylineV2CheckpointError("mixed model artifacts reset the evidence clock")
        slate_date = str(row.get("slate_date") or "")
        if slate_date != _utc_date(row.get("event_start_ts")):
            raise MLBMoneylineV2CheckpointError("slate_date must equal UTC event-start date")
        roi = _finite(row.get("paper_roi_fraction_per_1u"), "paper_roi_fraction_per_1u")
        close_status = str(row.get("close_status") or "")
        if close_status == "AVAILABLE":
            clv = _finite(row.get("clv_probability_points"), "clv_probability_points")
            if int(row.get("close_coverage_value", -1)) != 1:
                raise MLBMoneylineV2CheckpointError("available close coverage flag invalid")
            row["clv_probability_points"] = clv
        elif close_status == "MISSING":
            if row.get("clv_probability_points") is not None or int(row.get("close_coverage_value", -1)) != 0:
                raise MLBMoneylineV2CheckpointError("missing close semantics invalid")
        else:
            raise MLBMoneylineV2CheckpointError("close_status invalid")
        row["paper_roi_fraction_per_1u"] = roi
        validated.append(row)
    return sorted(validated, key=lambda row: (str(row["slate_date"]), int(row["game_pk"])))


def _warning_gate(
    warning_statuses: Mapping[str, Mapping[str, Any]] | None,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    allowed = set((policy.get("official_warning_signoff") or {}).get("allowed_statuses") or ())
    if warning_statuses is None:
        return {
            "attested": False,
            "all_cleared_or_signed_off": False,
            "blocking_warnings": ["WARNING_STATUS_ATTESTATION_REQUIRED"],
        }
    blocking: list[str] = []
    for name, record in sorted(warning_statuses.items()):
        status = str((record or {}).get("status") or "")
        if status not in allowed:
            blocking.append(str(name))
            continue
        if status == "SIGNED_OFF":
            for field in ("actor", "timestamp_utc", "reason", "evidence_reference"):
                if not str((record or {}).get(field) or ""):
                    blocking.append(str(name))
                    break
    return {
        "attested": True,
        "all_cleared_or_signed_off": not blocking,
        "blocking_warnings": blocking,
    }


def evaluate_v2_checkpoint(
    rows: Iterable[Mapping[str, Any]],
    *,
    binding: Mapping[str, Any] | None = None,
    policy_path: str | Path = DEFAULT_POLICY_PATH,
    warning_statuses: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Evaluate the current evidence clock without granting any authority."""
    lane = dict(binding or load_forward_lane_binding())
    policy = _load_policy(policy_path)
    validated = _validate_rows(rows, lane)
    n = len(validated)
    closes = [row for row in validated if row["close_status"] == "AVAILABLE"]
    clv_values = [float(row["clv_probability_points"]) for row in closes]
    clv_clusters = [str(row["slate_date"]) for row in closes]
    roi_values = [float(row["paper_roi_fraction_per_1u"]) for row in validated]
    distinct_games = len({int(row["game_pk"]) for row in validated})
    slate_clusters = len({str(row["slate_date"]) for row in validated})
    close_coverage = (len(closes) / n) if n else 0.0
    mean_roi = (sum(roi_values) / n) if n else None
    clv_ci = _cluster_cr1_mean_ci(clv_values, clv_clusters) if clv_values else {
        "mean": None,
        "standard_error_cr1": None,
        "student_t_df": None,
        "student_t_critical_975": None,
        "ci_95_lower": None,
        "ci_95_upper": None,
    }
    report: dict[str, Any] = {
        "schema_version": CHECKPOINT_VERSION,
        "policy_id": policy["policy_id"],
        "lane_id": lane["lane_id"],
        "lane_definition_sha256": lane["lane_definition_sha256"],
        "market_definition_sha256": lane["market_definition_sha256"],
        "policy_sha256": lane["policy_sha256"],
        "model_artifact_sha256": validated[0]["model_artifact_sha256"] if validated else None,
        "graded_bets": n,
        "distinct_games": distinct_games,
        "slate_clusters": slate_clusters,
        "close_rows_available": len(closes),
        "close_coverage": close_coverage,
        "mean_clv_probability_points": clv_ci["mean"],
        "clv_standard_error_cr1": clv_ci["standard_error_cr1"],
        "clv_student_t_df": clv_ci["student_t_df"],
        "clv_student_t_critical_975": clv_ci["student_t_critical_975"],
        "clv_95_ci_lower_pp": clv_ci["ci_95_lower"],
        "clv_95_ci_upper_pp": clv_ci["ci_95_upper"],
        "mean_roi_fraction": mean_roi,
        "fixed_checkpoints": list(_FIXED_CHECKPOINTS),
        "at_fixed_checkpoint": n in _FIXED_CHECKPOINTS,
        "continuous_peeking_for_promotion": False,
        "promotion_authority": False,
        "deployment_change_allowed": False,
        "staking_change_allowed": False,
        "official_change_allowed": False,
    }
    if n not in _FIXED_CHECKPOINTS:
        report.update({
            "status": "NOT_AT_FIXED_CHECKPOINT",
            "checkpoint": None,
            "target_state": None,
            "qualifies_for_target_state": False,
            "blocking_reasons": [],
        })
        return report

    checkpoint = n
    cfg = dict((policy.get("checkpoints") or {})[f"checkpoint_{checkpoint}"])
    blockers: list[str] = []
    if distinct_games < int(cfg["min_distinct_games"]):
        blockers.append("MIN_DISTINCT_GAMES_NOT_MET")
    if slate_clusters < int(cfg["min_slate_clusters"]):
        blockers.append("MIN_SLATE_CLUSTERS_NOT_MET")
    if close_coverage < float(cfg["min_close_coverage"]):
        blockers.append("MIN_CLOSE_COVERAGE_NOT_MET")
    if mean_roi is None or mean_roi < -float(cfg["max_roi_loss_fraction"]):
        blockers.append("ROI_KILL_THRESHOLD_BREACHED")

    min_interval_clusters = int(((policy.get("forward_capture") or {}).get("clv_inference") or {}).get("minimum_clusters_for_interval", 5))
    interval_ready = len(set(clv_clusters)) >= min_interval_clusters and clv_ci["ci_95_upper"] is not None
    if not interval_ready:
        blockers.append("CLV_INTERVAL_NOT_IDENTIFIED")
    elif float(clv_ci["ci_95_upper"]) < 0.0:
        blockers.append("CLV_95_CI_UPPER_BELOW_ZERO")

    warning_gate = None
    if checkpoint == 50:
        if clv_ci["mean"] is None or float(clv_ci["mean"]) < float(cfg["min_mean_clv_pp"]):
            blockers.append("MEAN_CLV_BELOW_CHECKPOINT_50_FLOOR")
    elif checkpoint == 150:
        if not interval_ready or float(clv_ci["ci_95_lower"]) <= float(cfg["clv_ci_lower_pp_must_be_above"]):
            blockers.append("CLV_95_CI_LOWER_NOT_ABOVE_ZERO")
        warning_gate = _warning_gate(warning_statuses, policy)
        if not warning_gate["all_cleared_or_signed_off"]:
            blockers.append("OFFICIAL_WARNING_REQUIREMENT_NOT_MET")

    target_state = str(cfg["target_state"])
    report.update({
        "status": "FIXED_CHECKPOINT_EVALUATED",
        "checkpoint": checkpoint,
        "target_state": target_state,
        "qualifies_for_target_state": not blockers,
        "blocking_reasons": sorted(set(blockers)),
        "warning_gate": warning_gate,
        "checkpoint_policy": cfg,
    })
    return report
