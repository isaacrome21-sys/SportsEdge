"""Fixed-checkpoint evaluator for prospective MLB MONEYLINE Promotion Evidence Policy V2.

This module is deliberately downstream of immutable V2 settlement rows. It never
changes Model_P, selects a bet, changes stake, or grants promotion/OFFICIAL
authority. It evaluates only the frozen first-N evidence prefixes at the policy's
50/100/150 checkpoints, which prevents continuous peeking from changing the
sample used at a checkpoint.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from math import exp, isfinite, lgamma, log, sqrt
from pathlib import Path
from typing import Any, Iterable, Mapping

from .mlb_moneyline_forward_lane import (
    MLBMoneylineForwardLaneError,
    load_forward_lane_binding,
    require_record_binding,
)
from .truth_gate import american_to_decimal

CHECKPOINT_REPORT_SCHEMA = "mlb_moneyline_promotion_checkpoint_v2"
EVIDENCE_SCHEMA = "mlb_moneyline_forward_evidence_v2"
POLICY_ID = "PROMOTION_EVIDENCE_POLICY_V2"


class MLBMoneylineV2CheckpointError(ValueError):
    pass


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    raw = json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _ts(value: Any, field: str) -> datetime:
    try:
        out = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise MLBMoneylineV2CheckpointError(f"{field}: invalid timestamp") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise MLBMoneylineV2CheckpointError(f"{field}: timezone required")
    return out.astimezone(timezone.utc)


def _finite(value: Any, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise MLBMoneylineV2CheckpointError(f"{field}: invalid number") from exc
    if not isfinite(out):
        raise MLBMoneylineV2CheckpointError(f"{field}: non-finite number")
    return out


def _load_policy(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise MLBMoneylineV2CheckpointError(f"policy load failed: {path}") from exc
    if not isinstance(value, dict) or value.get("policy_id") != POLICY_ID:
        raise MLBMoneylineV2CheckpointError("active V2 promotion policy required")
    checkpoints = value.get("checkpoints")
    if not isinstance(checkpoints, Mapping):
        raise MLBMoneylineV2CheckpointError("checkpoint policy missing")
    expected = [50, 100, 150]
    if list(checkpoints.get("evaluate_only_at_graded_counts") or ()) != expected:
        raise MLBMoneylineV2CheckpointError("frozen checkpoint counts changed")
    return value


def _betacf(a: float, b: float, x: float) -> float:
    # Numerical Recipes continued fraction for the incomplete beta function.
    max_iter = 300
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
    raise MLBMoneylineV2CheckpointError("student-t beta fraction did not converge")


def _regularized_beta(x: float, a: float, b: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    bt = exp(lgamma(a + b) - lgamma(a) - lgamma(b) + a * log(x) + b * log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def _student_t_cdf(t: float, df: int) -> float:
    if df < 1:
        raise MLBMoneylineV2CheckpointError("student-t degrees of freedom invalid")
    if t == 0.0:
        return 0.5
    x = df / (df + t * t)
    tail = 0.5 * _regularized_beta(x, df / 2.0, 0.5)
    return 1.0 - tail if t > 0.0 else tail


def _student_t_critical_975(df: int) -> float:
    lo, hi = 0.0, 64.0
    for _ in range(120):
        mid = (lo + hi) / 2.0
        if _student_t_cdf(mid, df) < 0.975:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _clustered_mean_interval(values: list[float], clusters: list[str]) -> dict[str, Any]:
    if len(values) != len(clusters) or not values:
        raise MLBMoneylineV2CheckpointError("CLV values/clusters missing")
    n = len(values)
    mean = sum(values) / n
    by_cluster: dict[str, float] = {}
    for value, cluster in zip(values, clusters):
        if not cluster:
            raise MLBMoneylineV2CheckpointError("slate_date required for CLV cluster")
        by_cluster[cluster] = by_cluster.get(cluster, 0.0) + (value - mean)
    g = len(by_cluster)
    if g < 2:
        return {
            "mean_clv_pp": mean,
            "clv_sample_count": n,
            "clv_cluster_count": g,
            "cr1_standard_error_pp": None,
            "student_t_df": None,
            "student_t_critical_975": None,
            "clv_95_ci_lower_pp": None,
            "clv_95_ci_upper_pp": None,
            "interval_status": "INSUFFICIENT_CLUSTERS",
        }
    meat = sum(score * score for score in by_cluster.values())
    variance = (g / (g - 1.0)) * meat / (n * n)
    se = sqrt(max(0.0, variance))
    critical = _student_t_critical_975(g - 1)
    return {
        "mean_clv_pp": mean,
        "clv_sample_count": n,
        "clv_cluster_count": g,
        "cr1_standard_error_pp": se,
        "student_t_df": g - 1,
        "student_t_critical_975": critical,
        "clv_95_ci_lower_pp": mean - critical * se,
        "clv_95_ci_upper_pp": mean + critical * se,
        "interval_status": "AVAILABLE",
    }


def _validate_row(row: Mapping[str, Any], binding: Mapping[str, Any]) -> dict[str, Any]:
    if row.get("schema_version") != EVIDENCE_SCHEMA:
        raise MLBMoneylineV2CheckpointError("legacy or unknown evidence schema is not V2")
    if row.get("status") != "FORWARD_EVIDENCE_COMPLETE_V2":
        raise MLBMoneylineV2CheckpointError("complete V2 evidence row required")
    if row.get("graded_bet") is not True or row.get("evidence_counts") is not True:
        raise MLBMoneylineV2CheckpointError("only valid non-BLOCKED graded bets count")
    if row.get("promotion_authority") is not False:
        raise MLBMoneylineV2CheckpointError("evidence row cannot carry promotion authority")
    try:
        require_record_binding(row, binding)
    except MLBMoneylineForwardLaneError as exc:
        raise MLBMoneylineV2CheckpointError(str(exc)) from exc

    decision = _ts(row.get("decision_frozen_at_utc"), "decision_frozen_at_utc")
    start = _ts(row.get("event_start_ts"), "event_start_ts")
    if not decision < start:
        raise MLBMoneylineV2CheckpointError("decision must precede event start")
    try:
        game_pk = int(row.get("game_pk"))
    except (TypeError, ValueError) as exc:
        raise MLBMoneylineV2CheckpointError("game_pk invalid") from exc
    slate = str(row.get("slate_date") or "")
    if not slate:
        raise MLBMoneylineV2CheckpointError("slate_date missing")
    outcome = row.get("outcome")
    if outcome not in (0, 1):
        raise MLBMoneylineV2CheckpointError("binary final outcome required")

    odds = _finite(row.get("entry_selected_odds"), "entry_selected_odds")
    expected_roi = american_to_decimal(odds) - 1.0 if outcome == 1 else -1.0
    roi = _finite(row.get("paper_roi_fraction_per_1u"), "paper_roi_fraction_per_1u")
    profit = _finite(row.get("paper_profit_units_per_1u"), "paper_profit_units_per_1u")
    if abs(roi - expected_roi) > 1e-10 or abs(profit - expected_roi) > 1e-10:
        raise MLBMoneylineV2CheckpointError("settlement ROI/profit mismatch")

    close_status = str(row.get("close_status") or "")
    coverage = row.get("close_coverage_value")
    clv: float | None
    if close_status == "AVAILABLE":
        if coverage != 1 or row.get("missing_close_excluded_from_clv") is not False:
            raise MLBMoneylineV2CheckpointError("available close flags invalid")
        close_ts = _ts(row.get("close_observed_at_utc"), "close_observed_at_utc")
        if not close_ts < start:
            raise MLBMoneylineV2CheckpointError("close must precede event start")
        entry_fair = _finite(row.get("entry_fair_probability"), "entry_fair_probability")
        close_fair = _finite(
            row.get("close_selected_fair_probability"), "close_selected_fair_probability"
        )
        clv = _finite(row.get("clv_probability_points"), "clv_probability_points")
        if abs(clv - (close_fair - entry_fair)) > 1e-10:
            raise MLBMoneylineV2CheckpointError("CLV identity mismatch")
    elif close_status == "MISSING":
        if coverage != 0 or row.get("missing_close_excluded_from_clv") is not True:
            raise MLBMoneylineV2CheckpointError("missing close flags invalid")
        if row.get("clv_probability_points") is not None:
            raise MLBMoneylineV2CheckpointError("missing close cannot carry CLV")
        clv = None
    else:
        raise MLBMoneylineV2CheckpointError("close_status invalid")
    if row.get("missing_close_counts_in_checkpoint_denominator") is not True:
        raise MLBMoneylineV2CheckpointError("checkpoint denominator flag invalid")

    return {
        "game_pk": game_pk,
        "slate_date": slate,
        "decision_ts": decision,
        "roi": roi,
        "clv": clv,
        "record_sha256": _canonical_sha256(row),
    }


def _checkpoint_policy(policy: Mapping[str, Any], count: int) -> Mapping[str, Any]:
    value = policy["checkpoints"].get(f"checkpoint_{count}")
    if not isinstance(value, Mapping):
        raise MLBMoneylineV2CheckpointError(f"checkpoint_{count} policy missing")
    return value


def _evaluate_prefix(
    rows: list[dict[str, Any]], *, count: int, policy: Mapping[str, Any]
) -> dict[str, Any]:
    prefix = rows[:count]
    cfg = _checkpoint_policy(policy, count)
    games = {row["game_pk"] for row in prefix}
    slates = {row["slate_date"] for row in prefix}
    close_rows = [row for row in prefix if row["clv"] is not None]
    close_coverage = len(close_rows) / count
    roi = sum(row["roi"] for row in prefix) / count
    interval_min_clusters = int(policy["forward_capture"]["clv_inference"]["minimum_clusters_for_interval"])
    if close_rows:
        interval = _clustered_mean_interval(
            [float(row["clv"]) for row in close_rows],
            [row["slate_date"] for row in close_rows],
        )
    else:
        interval = {
            "mean_clv_pp": None,
            "clv_sample_count": 0,
            "clv_cluster_count": 0,
            "cr1_standard_error_pp": None,
            "student_t_df": None,
            "student_t_critical_975": None,
            "clv_95_ci_lower_pp": None,
            "clv_95_ci_upper_pp": None,
            "interval_status": "NO_VALID_CLOSES",
        }

    min_games = int(cfg["min_distinct_games"])
    min_slates = int(cfg["min_slate_clusters"])
    min_coverage = float(cfg["min_close_coverage"])
    max_loss = float(cfg["max_roi_loss_fraction"])
    base_checks = {
        "graded_bets": count >= int(cfg["min_graded_bets"]),
        "distinct_games": len(games) >= min_games,
        "slate_clusters": len(slates) >= min_slates,
        "close_coverage": close_coverage >= min_coverage,
        "roi_loss_limit": roi >= -max_loss,
        "clv_interval_available": (
            interval["interval_status"] == "AVAILABLE"
            and int(interval["clv_cluster_count"]) >= interval_min_clusters
        ),
    }

    kill_rules: list[str] = []
    upper = interval.get("clv_95_ci_upper_pp")
    if upper is not None and float(upper) < 0.0:
        kill_rules.append("clv_95_ci_upper_pp < 0.0")
    if roi < -0.075:
        kill_rules.append("roi_fraction < -0.075")
    if close_coverage < 0.90:
        kill_rules.append("close_coverage < 0.90")

    metric_checks = dict(base_checks)
    if count == 50:
        mean = interval.get("mean_clv_pp")
        metric_checks["mean_clv_nonnegative"] = mean is not None and float(mean) >= float(
            cfg["min_mean_clv_pp"]
        )
    elif count == 100:
        metric_checks["no_checkpoint_kill_rule"] = not kill_rules
    elif count == 150:
        lower = interval.get("clv_95_ci_lower_pp")
        metric_checks["clv_ci_lower_above_zero"] = (
            lower is not None and float(lower) > float(cfg["clv_ci_lower_pp_must_be_above"])
        )

    metric_gate_pass = all(metric_checks.values()) and not kill_rules
    if count == 50:
        disposition = "PROBATION_METRICS_PASS" if metric_gate_pass else "PAPER_METRICS_FAIL"
    elif count == 100:
        disposition = (
            "PROBATION_CONTINUE_METRICS_PASS" if metric_gate_pass else "PAPER_DEMOTION_METRIC_TRIGGER"
        )
    else:
        disposition = (
            "OFFICIAL_CANDIDATE_METRICS_PASS" if metric_gate_pass else "OFFICIAL_CANDIDATE_METRICS_FAIL"
        )

    lineage = [row["record_sha256"] for row in prefix]
    return {
        "checkpoint_count": count,
        "target_state": cfg["target_state"],
        "sample_rule": f"FROZEN_FIRST_{count}_VALID_V2_GRADED_BETS",
        "graded_bet_count": count,
        "distinct_game_count": len(games),
        "slate_cluster_count": len(slates),
        "valid_close_count": len(close_rows),
        "missing_close_count": count - len(close_rows),
        "close_coverage": close_coverage,
        "roi_fraction_per_1u": roi,
        **interval,
        "metric_checks": metric_checks,
        "kill_rules_fired": kill_rules,
        "metric_gate_pass": metric_gate_pass,
        "metric_disposition": disposition,
        "required_before_entry_status": (
            "SEPARATE_GOVERNANCE_GATE_NOT_ASSERTED_BY_METRIC_EVALUATOR" if count == 50 else None
        ),
        "official_warning_gate_status": (
            "SEPARATE_REQUIRED_GATE_NOT_ASSERTED_BY_METRIC_EVALUATOR" if count == 150 else None
        ),
        "evidence_record_sha256s": lineage,
        "checkpoint_sample_sha256": hashlib.sha256("\n".join(lineage).encode("ascii")).hexdigest(),
        "promotion_authority": False,
        "deployment_change_allowed": False,
        "staking_change_allowed": False,
        "official_change_allowed": False,
    }


def evaluate_v2_checkpoints(
    evidence_rows: Iterable[Mapping[str, Any]],
    *,
    binding: Mapping[str, Any] | None = None,
    policy_path: str | Path = "config/promotion_evidence_policy_v2.json",
) -> dict[str, Any]:
    """Evaluate every crossed fixed checkpoint using only its frozen first-N prefix."""
    policy = _load_policy(policy_path)
    lane = dict(binding or load_forward_lane_binding())
    validated = [_validate_row(row, lane) for row in evidence_rows]
    validated.sort(key=lambda row: (row["decision_ts"], row["game_pk"]))

    game_ids = [row["game_pk"] for row in validated]
    if len(game_ids) != len(set(game_ids)):
        raise MLBMoneylineV2CheckpointError("DUPLICATE_OR_MUTATED_EVIDENCE_ROW")
    hashes = [row["record_sha256"] for row in validated]
    if len(hashes) != len(set(hashes)):
        raise MLBMoneylineV2CheckpointError("DUPLICATE_OR_MUTATED_EVIDENCE_ROW")

    fixed = [int(value) for value in policy["checkpoints"]["evaluate_only_at_graded_counts"]]
    crossed = [count for count in fixed if len(validated) >= count]
    evaluations = [_evaluate_prefix(validated, count=count, policy=policy) for count in crossed]
    next_checkpoint = next((count for count in fixed if len(validated) < count), None)
    return {
        "schema_version": CHECKPOINT_REPORT_SCHEMA,
        "policy_id": POLICY_ID,
        "lane_id": lane["lane_id"],
        "model_artifact_sha256": lane["model_artifact_sha256"],
        "market_definition_sha256": lane["market_definition_sha256"],
        "policy_sha256": lane["policy_sha256"],
        "total_valid_v2_graded_bets": len(validated),
        "fixed_checkpoint_counts": fixed,
        "crossed_checkpoint_counts": crossed,
        "next_checkpoint_count": next_checkpoint,
        "continuous_peeking_for_promotion": False,
        "checkpoint_evaluations": evaluations,
        "status": "CHECKPOINTS_EVALUATED" if evaluations else "WAITING_FOR_FIRST_CHECKPOINT",
        "promotion_authority": False,
        "deployment_change_allowed": False,
        "staking_change_allowed": False,
        "official_change_allowed": False,
    }
