"""Read-only terminal readiness intersection for governed MLB MONEYLINE authority.

This module cannot promote a market or edit deployment/staking state. Its only job
is to prove whether all already-frozen prerequisites have been observed together:
prospective calibration, V2 fixed-checkpoint evidence, model-directed no-vig close
edge, frozen floor, and current deployment state. Any missing evidence remains a
blocker and every authority flag emitted here is always false.
"""
from __future__ import annotations

import argparse
import json
from math import isfinite
from pathlib import Path
import sys
from typing import Any, Mapping

from .mlb_moneyline_clv import MLBMoneylineCLVError, evaluate_paired_closes
from .mlb_moneyline_forward_lane import load_forward_lane_binding
from .mlb_moneyline_v2_checkpoint_runtime import load_evidence_tree

READINESS_SCHEMA = "mlb_moneyline_authority_readiness_v1"
DEFAULT_CALIBRATION_REPORT = "artifacts/mlb_moneyline_forward_calibration_report.json"
DEFAULT_CHECKPOINT_REPORT = "artifacts/mlb_moneyline_v2_checkpoint_report.json"
DEFAULT_EVIDENCE_ROOT = "data/mlb_forward_evidence"
DEFAULT_REPORT = "artifacts/mlb_moneyline_authority_readiness_report.json"


class MLBMoneylineAuthorityReadinessError(RuntimeError):
    pass


def _load(path: str | Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise MLBMoneylineAuthorityReadinessError(f"{label} unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise MLBMoneylineAuthorityReadinessError(f"{label} must be an object")
    return value


def _finite(value: Any, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise MLBMoneylineAuthorityReadinessError(f"{field} invalid") from exc
    if not isfinite(out):
        raise MLBMoneylineAuthorityReadinessError(f"{field} non-finite")
    return out


def _checkpoint_150(report: Mapping[str, Any]) -> Mapping[str, Any] | None:
    for item in report.get("checkpoint_evaluations") or ():
        if isinstance(item, Mapping) and int(item.get("checkpoint_count", -1)) == 150:
            return item
    return None


def evaluate_authority_readiness(
    *,
    calibration_report: Mapping[str, Any],
    checkpoint_report: Mapping[str, Any],
    evidence_rows: list[Mapping[str, Any]],
    deployments: Mapping[str, Any],
    floor_config: Mapping[str, Any],
    binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    lane = dict(binding or load_forward_lane_binding())
    active_artifact = str(lane.get("model_artifact_sha256") or "")
    if len(active_artifact) != 64:
        active_artifact = str(
            checkpoint_report.get("model_artifact_sha256")
            or calibration_report.get("model_artifact_sha256")
            or ""
        )
    if len(active_artifact) != 64:
        raise MLBMoneylineAuthorityReadinessError("active model artifact identity unavailable")

    cal_metrics = calibration_report.get("calibration_metrics")
    if not isinstance(cal_metrics, Mapping):
        cal_metrics = {}
    cal_thresholds = cal_metrics.get("thresholds") if isinstance(cal_metrics, Mapping) else None
    threshold_contract_ok = bool(
        isinstance(cal_thresholds, Mapping)
        and int(cal_thresholds.get("min_sample", -1)) == 200
        and list(cal_thresholds.get("slope") or ()) == [0.9, 1.1]
        and _finite(cal_thresholds.get("abs_intercept_max"), "abs_intercept_max") == 0.03
        and _finite(cal_thresholds.get("ece_max"), "ece_max") == 0.025
    )
    calibration_metrics_present = all(
        key in cal_metrics
        for key in ("brier", "log_loss", "calibration_slope", "calibration_intercept", "ece")
    )
    if calibration_metrics_present:
        for key in ("brier", "log_loss", "calibration_slope", "calibration_intercept", "ece"):
            _finite(cal_metrics.get(key), key)
    calibration_pass = bool(
        threshold_contract_ok
        and calibration_metrics_present
        and cal_metrics.get("sample_gate_pass") is True
        and cal_metrics.get("calibration_gate_pass") is True
        and int(cal_metrics.get("n", 0)) >= 200
    )

    cp150 = _checkpoint_150(checkpoint_report)
    checkpoint_150_pass = bool(
        cp150
        and cp150.get("metric_gate_pass") is True
        and cp150.get("metric_disposition") == "OFFICIAL_CANDIDATE_METRICS_PASS"
        and int(cp150.get("graded_bet_count", 0)) == 150
        and _finite(cp150.get("close_coverage"), "checkpoint close_coverage") >= 0.90
        and cp150.get("clv_95_ci_lower_pp") is not None
        and _finite(cp150.get("clv_95_ci_lower_pp"), "checkpoint CLV lower") > 0.0
        and _finite(cp150.get("roi_fraction_per_1u"), "checkpoint ROI") >= -0.075
    )

    close_rows = [
        dict(row)
        for row in evidence_rows
        if row.get("schema_version") == "mlb_moneyline_forward_evidence_v2"
        and row.get("status") == "FORWARD_EVIDENCE_COMPLETE_V2"
        and row.get("close_status") == "AVAILABLE"
        and str(row.get("model_artifact_sha256") or "") == active_artifact
    ]
    try:
        clv = evaluate_paired_closes(close_rows, min_mean_clv=0.005)
    except MLBMoneylineCLVError as exc:
        raise MLBMoneylineAuthorityReadinessError(str(exc)) from exc
    model_directed_clv_pass = bool(
        clv.get("clv_gate_pass") is True and int(clv.get("n", 0)) > 0
    )

    truth_gate = floor_config.get("truth_gate") or {}
    production = truth_gate.get("production") or {}
    floor_policy = truth_gate.get("floor_policy") or {}
    edge_floors = truth_gate.get("edge_floors") or {}
    mlb = edge_floors.get("MLB") or {}
    floor_pass = bool(
        truth_gate.get("schema_version") == 3
        and production.get("fail_closed") is True
        and production.get("allow_cli_floor_override") is False
        and production.get("require_frozen_floor_for_eligible_market") is True
        and floor_policy.get("status") == "FROZEN_BEFORE_JUDGED_STREAM"
        and _finite(floor_policy.get("default_floor"), "default floor") == 0.03
        and _finite(floor_policy.get("longshot_or_one_sided_floor"), "longshot floor") == 0.05
        and _finite(mlb.get("moneyline"), "MLB moneyline floor") == 0.03
    )

    moneyline = ((deployments.get("markets") or {}).get("MONEYLINE") or {})
    deployment_currently_locked = moneyline.get("eligible") is False
    if moneyline.get("eligible") is True and not (
        calibration_pass and checkpoint_150_pass and model_directed_clv_pass and floor_pass
    ):
        raise MLBMoneylineAuthorityReadinessError(
            "MONEYLINE eligible before terminal evidence prerequisites"
        )

    checks = {
        "frozen_nonzero_edge_floor": floor_pass,
        "prospective_calibration_min_200_and_band_pass": calibration_pass,
        "v2_checkpoint_150_official_candidate_metrics_pass": checkpoint_150_pass,
        "model_directed_no_vig_close_edge_at_least_0_005": model_directed_clv_pass,
        "deployment_remains_fail_closed_until_transition": deployment_currently_locked,
    }
    evidence_complete = all(checks.values())
    if evidence_complete:
        status = "TERMINAL_EVIDENCE_PREREQUISITES_OBSERVED_TRANSITION_STILL_REQUIRED"
    elif not calibration_pass:
        status = "WAITING_FOR_CALIBRATION_GATE"
    elif not checkpoint_150_pass:
        status = "WAITING_FOR_V2_CHECKPOINT_150"
    elif not model_directed_clv_pass:
        status = "WAITING_FOR_MODEL_DIRECTED_CLV_GATE"
    else:
        status = "BLOCKED_TERMINAL_GOVERNANCE_PREREQUISITE"

    return {
        "schema_version": READINESS_SCHEMA,
        "status": status,
        "lane_id": lane["lane_id"],
        "model_artifact_sha256": active_artifact,
        "market_definition_sha256": lane["market_definition_sha256"],
        "policy_id": lane["policy_id"],
        "policy_sha256": lane["policy_sha256"],
        "checks": checks,
        "all_terminal_evidence_prerequisites_observed": evidence_complete,
        "calibration": dict(cal_metrics),
        "v2_checkpoint_150": dict(cp150) if cp150 else None,
        "model_directed_clv": clv,
        "deployment_snapshot": dict(moneyline),
        "warning_gate_status": "SEPARATE_OFFICIAL_WARNING_CLEARANCE_REQUIRED_AT_TRANSITION",
        "transition_rule": (
            "This receipt is read-only. A separate governed transition must verify warning "
            "clearance and fresh runtime hard checks before any deployment, stake, or OFFICIAL change."
        ),
        "promotion_authority": False,
        "deployment_change_allowed": False,
        "staking_change_allowed": False,
        "official_change_allowed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration-report", default=DEFAULT_CALIBRATION_REPORT)
    parser.add_argument("--checkpoint-report", default=DEFAULT_CHECKPOINT_REPORT)
    parser.add_argument("--evidence-root", default=DEFAULT_EVIDENCE_ROOT)
    parser.add_argument("--deployments", default="config/deployments.json")
    parser.add_argument("--floors", default="config/truth_gate_floors.json")
    parser.add_argument("--report", default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    try:
        calibration = _load(args.calibration_report, "calibration report")
        checkpoint = _load(args.checkpoint_report, "checkpoint report")
        deployments = _load(args.deployments, "deployments")
        floors = _load(args.floors, "truth gate floors")
        rows = load_evidence_tree(args.evidence_root)
        report = evaluate_authority_readiness(
            calibration_report=calibration,
            checkpoint_report=checkpoint,
            evidence_rows=rows,
            deployments=deployments,
            floor_config=floors,
        )
        rc = 0
    except Exception as exc:
        report = {
            "schema_version": READINESS_SCHEMA,
            "status": "BLOCKED_READINESS_RUNTIME_ERROR",
            "reason": str(exc),
            "promotion_authority": False,
            "deployment_change_allowed": False,
            "staking_change_allowed": False,
            "official_change_allowed": False,
        }
        rc = 2
    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return rc


if __name__ == "__main__":
    sys.exit(main())
