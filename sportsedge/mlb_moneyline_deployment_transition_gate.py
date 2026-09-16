"""Final non-authoritative intersection before an MLB MONEYLINE deployment transition.

This module combines the completed governance-documentation receipt with a genuinely
fresh runtime hard-check receipt.  It is intentionally unable to edit deployments,
change stake, grant promotion, or emit OFFICIAL bets.  Its only successful output
is a hash-bound receipt showing that the prerequisite documents and live runtime
observation agree while the production deployment is still fail closed.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping

SCHEMA = "mlb_moneyline_deployment_transition_gate_v1"
READY_STATUS = "DEPLOYMENT_TRANSITION_PREREQUISITES_SATISFIED_NON_AUTHORITATIVE"
READINESS_SCHEMA = "mlb_moneyline_transition_readiness_v1"
READINESS_STATUS = "GOVERNANCE_DOCUMENTATION_COMPLETE_FRESH_RUNTIME_STILL_REQUIRED"
RUNTIME_SCHEMA = "mlb_moneyline_fresh_runtime_hard_checks_v1"
RUNTIME_STATUS = "FRESH_RUNTIME_HARD_CHECKS_PASS"
MAX_RUNTIME_RECEIPT_AGE_SECONDS = 120.0


class MLBMoneylineDeploymentTransitionGateError(RuntimeError):
    pass


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _ts(value: Any, field: str) -> datetime:
    try:
        out = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise MLBMoneylineDeploymentTransitionGateError(f"{field}: invalid timestamp") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise MLBMoneylineDeploymentTransitionGateError(f"{field}: timezone required")
    return out.astimezone(timezone.utc)


def _utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise MLBMoneylineDeploymentTransitionGateError(f"{field}: timezone required")
    return value.astimezone(timezone.utc)


def _sha(value: Any, field: str) -> str:
    text = str(value or "").lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise MLBMoneylineDeploymentTransitionGateError(f"{field}: invalid sha256")
    return text


def _require_non_authority(value: Mapping[str, Any], label: str) -> None:
    if value.get("state_transition_apply_now") is not False:
        raise MLBMoneylineDeploymentTransitionGateError(
            f"{label} must not apply a state transition"
        )
    for field in (
        "promotion_authority",
        "deployment_change_allowed",
        "staking_change_allowed",
        "official_change_allowed",
    ):
        if value.get(field) is not False:
            raise MLBMoneylineDeploymentTransitionGateError(
                f"{label} carries forbidden authority: {field}"
            )


def _identity(value: Mapping[str, Any], label: str) -> dict[str, str]:
    out = {
        "lane_id": str(value.get("lane_id") or ""),
        "model_artifact_sha256": _sha(value.get("model_artifact_sha256"), f"{label} model artifact"),
        "market_definition_sha256": _sha(value.get("market_definition_sha256"), f"{label} market definition"),
        "policy_id": str(value.get("policy_id") or ""),
        "policy_sha256": _sha(value.get("policy_sha256"), f"{label} policy"),
    }
    if not out["lane_id"] or not out["policy_id"]:
        raise MLBMoneylineDeploymentTransitionGateError(f"{label} identity incomplete")
    return out


def evaluate_deployment_transition_gate(
    *,
    transition_readiness: Mapping[str, Any],
    fresh_runtime_receipt: Mapping[str, Any],
    deployments: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any]:
    """Return a non-authoritative transition receipt or fail closed."""

    now_utc = _utc(now, "now")

    if transition_readiness.get("schema_version") != READINESS_SCHEMA:
        raise MLBMoneylineDeploymentTransitionGateError("transition readiness schema mismatch")
    if transition_readiness.get("status") != READINESS_STATUS:
        raise MLBMoneylineDeploymentTransitionGateError("governance documentation not complete")
    if transition_readiness.get("governance_documentation_complete") is not True:
        raise MLBMoneylineDeploymentTransitionGateError("governance documentation flag not complete")
    if transition_readiness.get("fresh_runtime_hard_checks_required") is not True:
        raise MLBMoneylineDeploymentTransitionGateError("fresh runtime requirement missing")
    _require_non_authority(transition_readiness, "transition readiness")

    if fresh_runtime_receipt.get("schema_version") != RUNTIME_SCHEMA:
        raise MLBMoneylineDeploymentTransitionGateError("fresh runtime schema mismatch")
    if fresh_runtime_receipt.get("status") != RUNTIME_STATUS:
        raise MLBMoneylineDeploymentTransitionGateError("fresh runtime hard checks did not pass")
    if fresh_runtime_receipt.get("deployment_eligible_during_check") is not False:
        raise MLBMoneylineDeploymentTransitionGateError(
            "fresh runtime receipt was not generated fail closed"
        )
    runtime_checks = fresh_runtime_receipt.get("runtime_checks")
    if not isinstance(runtime_checks, Mapping) or not runtime_checks or not all(
        value is True for value in runtime_checks.values()
    ):
        raise MLBMoneylineDeploymentTransitionGateError("fresh runtime check set incomplete")
    _require_non_authority(fresh_runtime_receipt, "fresh runtime receipt")

    readiness_identity = _identity(transition_readiness, "transition readiness")
    runtime_identity = _identity(fresh_runtime_receipt, "fresh runtime receipt")
    if readiness_identity != runtime_identity:
        raise MLBMoneylineDeploymentTransitionGateError("fresh runtime identity drift")

    readiness_sha = _canonical_sha256(dict(transition_readiness))
    if str(fresh_runtime_receipt.get("transition_readiness_sha256") or "") != readiness_sha:
        raise MLBMoneylineDeploymentTransitionGateError(
            "fresh runtime receipt does not bind exact transition readiness"
        )

    markets = deployments.get("markets")
    if not isinstance(markets, Mapping):
        raise MLBMoneylineDeploymentTransitionGateError("deployments markets unavailable")
    moneyline = markets.get("MONEYLINE")
    if not isinstance(moneyline, Mapping):
        raise MLBMoneylineDeploymentTransitionGateError("MONEYLINE deployment unavailable")
    if moneyline.get("eligible") is not False:
        raise MLBMoneylineDeploymentTransitionGateError(
            "MONEYLINE must remain eligible=false before transition"
        )
    deployment_sha = _canonical_sha256(dict(moneyline))
    readiness_deployment_sha = _sha(
        transition_readiness.get("deployment_snapshot_sha256"),
        "transition readiness deployment snapshot",
    )
    runtime_deployment_sha = _sha(
        fresh_runtime_receipt.get("deployment_snapshot_sha256"),
        "fresh runtime deployment snapshot",
    )
    if deployment_sha != readiness_deployment_sha or deployment_sha != runtime_deployment_sha:
        raise MLBMoneylineDeploymentTransitionGateError("deployment snapshot drift")

    quote_observed = _ts(
        fresh_runtime_receipt.get("quote_observed_at_utc"), "quote_observed_at_utc"
    )
    event_start = _ts(fresh_runtime_receipt.get("event_start_ts"), "event_start_ts")
    if not quote_observed < now_utc < event_start:
        raise MLBMoneylineDeploymentTransitionGateError(
            "transition gate must run after quote observation and before event start"
        )
    receipt_age = (now_utc - quote_observed).total_seconds()
    if receipt_age > MAX_RUNTIME_RECEIPT_AGE_SECONDS:
        raise MLBMoneylineDeploymentTransitionGateError("fresh runtime receipt expired")

    try:
        runtime_quote_age = float(fresh_runtime_receipt.get("quote_age_seconds"))
        runtime_max_quote_age = float(fresh_runtime_receipt.get("max_quote_age_seconds"))
    except (TypeError, ValueError) as exc:
        raise MLBMoneylineDeploymentTransitionGateError(
            "fresh runtime quote age contract invalid"
        ) from exc
    if runtime_quote_age < 0 or runtime_max_quote_age <= 0 or runtime_quote_age > runtime_max_quote_age:
        raise MLBMoneylineDeploymentTransitionGateError(
            "fresh runtime quote was not fresh when attested"
        )
    if runtime_max_quote_age > 60.0:
        raise MLBMoneylineDeploymentTransitionGateError(
            "fresh runtime quote freshness ceiling widened"
        )

    return {
        "schema_version": SCHEMA,
        "status": READY_STATUS,
        **readiness_identity,
        "transition_readiness_sha256": readiness_sha,
        "fresh_runtime_receipt_sha256": _canonical_sha256(dict(fresh_runtime_receipt)),
        "deployment_snapshot_sha256": deployment_sha,
        "game_pk": int(fresh_runtime_receipt.get("game_pk")),
        "provider_event_id": str(fresh_runtime_receipt.get("provider_event_id") or ""),
        "event_start_ts": event_start.isoformat(),
        "quote_observed_at_utc": quote_observed.isoformat(),
        "transition_gate_checked_at_utc": now_utc.isoformat(),
        "runtime_receipt_age_seconds": receipt_age,
        "max_runtime_receipt_age_seconds": MAX_RUNTIME_RECEIPT_AGE_SECONDS,
        "deployment_eligible_during_gate": False,
        "prerequisites": {
            "governance_documentation_complete": True,
            "official_warning_clearance_bound": True,
            "fresh_runtime_hard_checks_pass": True,
            "exact_identity_match": True,
            "exact_deployment_snapshot_match": True,
            "fresh_runtime_receipt_not_expired": True,
            "event_not_started": True,
        },
        "state_transition_apply_now": False,
        "transition_rule": (
            "This receipt proves prerequisites only. It does not itself mutate deployments, "
            "grant promotion, authorize staking, or emit OFFICIAL. A separate controlled "
            "deployment-state change must consume this exact receipt and revalidate identity."
        ),
        "promotion_authority": False,
        "deployment_change_allowed": False,
        "staking_change_allowed": False,
        "official_change_allowed": False,
    }
