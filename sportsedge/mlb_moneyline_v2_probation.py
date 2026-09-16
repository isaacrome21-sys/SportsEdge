"""Fail-closed PROBATION transition-readiness gate for MLB MONEYLINE V2.

This module consumes the fixed checkpoint-50 receipt plus an explicit prerequisite
attestation.  It can declare a transition *ready for authority review*, but it
never mutates deployments, creates stake, or grants promotion/OFFICIAL authority.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .mlb_model_artifact import mlb_model_artifact_sha256
from .mlb_moneyline_forward_lane import load_forward_lane_binding
from .mlb_moneyline_v2_checkpoint import CHECKPOINT_REPORT_SCHEMA, POLICY_ID

READINESS_SCHEMA = "mlb_moneyline_v2_probation_readiness_v1"
ATTESTATION_SCHEMA = "mlb_moneyline_v2_probation_prerequisites_v1"
DEFAULT_POLICY_PATH = Path("config/promotion_evidence_policy_v2.json")


class MLBMoneylineV2ProbationError(ValueError):
    pass


def _load_policy(path: str | Path = DEFAULT_POLICY_PATH) -> dict[str, Any]:
    policy_path = Path(path)
    if not policy_path.is_absolute():
        policy_path = Path(__file__).resolve().parents[1] / policy_path
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise MLBMoneylineV2ProbationError("promotion policy unreadable") from exc
    if not isinstance(policy, dict) or policy.get("policy_id") != POLICY_ID:
        raise MLBMoneylineV2ProbationError("active V2 promotion policy required")
    cfg = (policy.get("checkpoints") or {}).get("checkpoint_50")
    if not isinstance(cfg, Mapping) or cfg.get("target_state") != "PROBATION":
        raise MLBMoneylineV2ProbationError("checkpoint-50 PROBATION policy missing")
    required = cfg.get("required_before_entry")
    if not isinstance(required, list) or not required or any(not isinstance(v, str) or not v for v in required):
        raise MLBMoneylineV2ProbationError("checkpoint-50 prerequisite contract invalid")
    if float((policy.get("states") or {}).get("PROBATION", {}).get("stake_units_per_bet", -1)) != 0.25:
        raise MLBMoneylineV2ProbationError("frozen PROBATION stake contract mismatch")
    return policy


def _sha256_text_lineage(values: list[str]) -> str:
    return hashlib.sha256("\n".join(values).encode("ascii")).hexdigest()


def _hex64(value: Any) -> str:
    text = str(value or "")
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise MLBMoneylineV2ProbationError("64-char lowercase SHA256 required")
    return text


def _active_identity(binding: Mapping[str, Any] | None = None) -> dict[str, str]:
    lane = dict(binding or load_forward_lane_binding())
    return {
        "lane_id": str(lane["lane_id"]),
        "model_artifact_sha256": mlb_model_artifact_sha256(),
        "market_definition_sha256": str(lane["market_definition_sha256"]),
        "policy_sha256": str(lane["policy_sha256"]),
    }


def _validate_checkpoint_report(
    report: Mapping[str, Any], active: Mapping[str, str]
) -> Mapping[str, Any] | None:
    if report.get("schema_version") != CHECKPOINT_REPORT_SCHEMA:
        raise MLBMoneylineV2ProbationError("checkpoint report schema mismatch")
    if report.get("policy_id") != POLICY_ID:
        raise MLBMoneylineV2ProbationError("checkpoint report policy mismatch")
    for key, expected in active.items():
        if str(report.get(key) or "") != expected:
            raise MLBMoneylineV2ProbationError(f"checkpoint report active identity mismatch: {key}")
    if report.get("promotion_authority") is not False:
        raise MLBMoneylineV2ProbationError("checkpoint report cannot carry promotion authority")
    evaluations = report.get("checkpoint_evaluations")
    if not isinstance(evaluations, list):
        raise MLBMoneylineV2ProbationError("checkpoint evaluations missing")
    matches = [item for item in evaluations if isinstance(item, Mapping) and item.get("checkpoint_count") == 50]
    if len(matches) > 1:
        raise MLBMoneylineV2ProbationError("duplicate checkpoint-50 evaluation")
    if not matches:
        total = int(report.get("total_valid_v2_graded_bets", 0))
        if total >= 50:
            raise MLBMoneylineV2ProbationError("checkpoint-50 evaluation missing after threshold crossed")
        return None
    cp = matches[0]
    if cp.get("target_state") != "PROBATION" or int(cp.get("graded_bet_count", -1)) != 50:
        raise MLBMoneylineV2ProbationError("checkpoint-50 target/count mismatch")
    lineage = cp.get("evidence_record_sha256s")
    if not isinstance(lineage, list) or len(lineage) != 50:
        raise MLBMoneylineV2ProbationError("checkpoint-50 lineage must contain exactly 50 rows")
    hashes = [_hex64(value) for value in lineage]
    if len(set(hashes)) != 50:
        raise MLBMoneylineV2ProbationError("checkpoint-50 lineage must be unique")
    sample_sha = _hex64(cp.get("checkpoint_sample_sha256"))
    if _sha256_text_lineage(hashes) != sample_sha:
        raise MLBMoneylineV2ProbationError("checkpoint-50 sample SHA mismatch")
    return cp


def _validate_attestation(
    attestation: Mapping[str, Any] | None,
    *,
    active: Mapping[str, str],
    checkpoint_sample_sha256: str,
    required: list[str],
) -> tuple[dict[str, Any], list[str]]:
    if attestation is None:
        return (
            {key: {"status": "MISSING", "evidence_reference": None} for key in required},
            list(required),
        )
    if attestation.get("schema_version") != ATTESTATION_SCHEMA:
        raise MLBMoneylineV2ProbationError("probation prerequisite attestation schema mismatch")
    if attestation.get("policy_id") != POLICY_ID:
        raise MLBMoneylineV2ProbationError("probation prerequisite attestation policy mismatch")
    for key, expected in active.items():
        if str(attestation.get(key) or "") != expected:
            raise MLBMoneylineV2ProbationError(f"probation prerequisite attestation identity mismatch: {key}")
    if str(attestation.get("checkpoint_sample_sha256") or "") != checkpoint_sample_sha256:
        raise MLBMoneylineV2ProbationError("probation prerequisite attestation checkpoint mismatch")
    requirements = attestation.get("requirements")
    if not isinstance(requirements, Mapping):
        raise MLBMoneylineV2ProbationError("probation prerequisite requirements missing")
    if set(requirements) != set(required):
        raise MLBMoneylineV2ProbationError("probation prerequisite key set mismatch")
    normalized: dict[str, Any] = {}
    missing: list[str] = []
    for name in required:
        record = requirements.get(name)
        if not isinstance(record, Mapping):
            raise MLBMoneylineV2ProbationError(f"probation prerequisite record invalid: {name}")
        status = str(record.get("status") or "")
        ref = str(record.get("evidence_reference") or "").strip()
        if status == "PASS" and not ref:
            raise MLBMoneylineV2ProbationError(f"PASS prerequisite requires evidence reference: {name}")
        if status not in {"PASS", "MISSING", "FAIL"}:
            raise MLBMoneylineV2ProbationError(f"probation prerequisite status invalid: {name}")
        normalized[name] = {"status": status, "evidence_reference": ref or None}
        if status != "PASS":
            missing.append(name)
    return normalized, missing


def evaluate_probation_readiness(
    checkpoint_report: Mapping[str, Any],
    *,
    prerequisite_attestation: Mapping[str, Any] | None = None,
    binding: Mapping[str, Any] | None = None,
    policy_path: str | Path = DEFAULT_POLICY_PATH,
) -> dict[str, Any]:
    """Return a non-authoritative readiness receipt for checkpoint-50 PROBATION."""
    policy = _load_policy(policy_path)
    active = _active_identity(binding)
    cp = _validate_checkpoint_report(checkpoint_report, active)
    required = list(policy["checkpoints"]["checkpoint_50"]["required_before_entry"])
    base = {
        "schema_version": READINESS_SCHEMA,
        "policy_id": POLICY_ID,
        **active,
        "candidate_state": "PROBATION",
        "stake_units_per_bet_from_policy": 0.25,
        "required_before_entry": required,
        "promotion_authority": False,
        "deployment_change_allowed": False,
        "staking_change_allowed": False,
        "official_change_allowed": False,
    }
    if cp is None:
        return {
            **base,
            "status": "WAITING_FOR_CHECKPOINT_50",
            "checkpoint_sample_sha256": None,
            "checkpoint_metric_disposition": None,
            "prerequisites": {key: {"status": "NOT_YET_EVALUATED", "evidence_reference": None} for key in required},
            "blocking_reasons": ["CHECKPOINT_50_NOT_REACHED"],
            "transition_ready_for_authority_review": False,
        }

    sample_sha = _hex64(cp.get("checkpoint_sample_sha256"))
    metric_pass = cp.get("metric_gate_pass") is True and cp.get("metric_disposition") == "PROBATION_METRICS_PASS"
    if cp.get("kill_rules_fired"):
        metric_pass = False
    prerequisites, missing = _validate_attestation(
        prerequisite_attestation,
        active=active,
        checkpoint_sample_sha256=sample_sha,
        required=required,
    )
    blockers: list[str] = []
    if not metric_pass:
        blockers.append("CHECKPOINT_50_METRICS_NOT_MET")
    blockers.extend(f"PREREQUISITE_NOT_PASS:{name}" for name in missing)
    ready = not blockers
    return {
        **base,
        "status": "PROBATION_TRANSITION_READY_FOR_AUTHORITY_REVIEW" if ready else "PROBATION_TRANSITION_NOT_READY",
        "checkpoint_sample_sha256": sample_sha,
        "checkpoint_metric_disposition": cp.get("metric_disposition"),
        "checkpoint_metric_gate_pass": cp.get("metric_gate_pass") is True,
        "checkpoint_kill_rules_fired": list(cp.get("kill_rules_fired") or ()),
        "prerequisites": prerequisites,
        "blocking_reasons": blockers,
        "transition_ready_for_authority_review": ready,
    }
