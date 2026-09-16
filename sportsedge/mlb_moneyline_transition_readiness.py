"""Read-only governance intersection before any MLB MONEYLINE state transition.

This module combines the terminal transition packet with an explicit OFFICIAL
warning-clearance receipt.  It does not inspect live odds, select a bet, edit
``deployments.json``, change stake, or grant promotion/OFFICIAL authority.  A
fresh runtime hard-check receipt remains a separate mandatory condition.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .mlb_moneyline_warning_clearance import validate_warning_clearance

SCHEMA = "mlb_moneyline_transition_readiness_v1"
PACKET_SCHEMA = "mlb_moneyline_transition_packet_v1"
PACKET_READY = "READY_FOR_FRESH_RUNTIME_AND_WARNING_CLEARANCE"
READY_STATUS = "GOVERNANCE_DOCUMENTATION_COMPLETE_FRESH_RUNTIME_STILL_REQUIRED"
WAITING_STATUS = "WAITING_FOR_OFFICIAL_WARNING_CLEARANCE"


class MLBMoneylineTransitionReadinessError(RuntimeError):
    pass


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _identity(packet: Mapping[str, Any]) -> dict[str, str]:
    out = {
        "lane_id": str(packet.get("lane_id") or ""),
        "model_artifact_sha256": str(packet.get("model_artifact_sha256") or ""),
        "market_definition_sha256": str(packet.get("market_definition_sha256") or ""),
        "policy_id": str(packet.get("policy_id") or ""),
        "policy_sha256": str(packet.get("policy_sha256") or ""),
    }
    if not out["lane_id"] or not out["policy_id"]:
        raise MLBMoneylineTransitionReadinessError("transition packet identity incomplete")
    for field in ("model_artifact_sha256", "market_definition_sha256", "policy_sha256"):
        value = out[field]
        if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise MLBMoneylineTransitionReadinessError(
                f"transition packet identity invalid: {field}"
            )
    return out


def _require_no_authority(value: Mapping[str, Any], label: str) -> None:
    for field in (
        "promotion_authority",
        "deployment_change_allowed",
        "staking_change_allowed",
        "official_change_allowed",
    ):
        if value.get(field) is not False:
            raise MLBMoneylineTransitionReadinessError(
                f"{label} must remain non-authoritative: {field}"
            )


def evaluate_transition_readiness(
    *,
    transition_packet: Mapping[str, Any],
    warning_receipt: Mapping[str, Any] | None,
    deployments: Mapping[str, Any],
) -> dict[str, Any]:
    if transition_packet.get("schema_version") != PACKET_SCHEMA:
        raise MLBMoneylineTransitionReadinessError("transition packet schema mismatch")
    if transition_packet.get("status") != PACKET_READY:
        raise MLBMoneylineTransitionReadinessError("transition packet not ready")
    _require_no_authority(transition_packet, "transition packet")

    required = list(transition_packet.get("required_transition_receipts") or ())
    if required != ["FRESH_RUNTIME_HARD_CHECKS_PASS", "OFFICIAL_WARNING_CLEARANCE_PASS"]:
        raise MLBMoneylineTransitionReadinessError("transition receipt contract mismatch")

    proposed = transition_packet.get("proposed_state_change")
    if not isinstance(proposed, Mapping) or dict(proposed) != {
        "market": "MONEYLINE",
        "from_eligible": False,
        "to_eligible": True,
        "apply_now": False,
    }:
        raise MLBMoneylineTransitionReadinessError("transition proposal contract mismatch")

    markets = deployments.get("markets")
    if not isinstance(markets, Mapping):
        raise MLBMoneylineTransitionReadinessError("deployments markets unavailable")
    moneyline = markets.get("MONEYLINE")
    if not isinstance(moneyline, Mapping):
        raise MLBMoneylineTransitionReadinessError("MONEYLINE deployment unavailable")
    if moneyline.get("eligible") is not False:
        raise MLBMoneylineTransitionReadinessError(
            "MONEYLINE must remain fail closed before state transition"
        )
    snapshot_sha = _canonical_sha256(dict(moneyline))
    if snapshot_sha != str(transition_packet.get("deployment_snapshot_sha256") or ""):
        raise MLBMoneylineTransitionReadinessError("deployment snapshot drift")

    identity = _identity(transition_packet)
    warning_status = None
    warning_sha = None
    if warning_receipt is not None:
        try:
            warning = validate_warning_clearance(
                warning_receipt,
                expected_identity=identity,
            )
        except Exception as exc:
            raise MLBMoneylineTransitionReadinessError(str(exc)) from exc
        warning_status = warning["status"]
        warning_sha = warning["receipt_sha256"]

    documentation_complete = warning_status == "OFFICIAL_WARNING_CLEARANCE_PASS"
    status = READY_STATUS if documentation_complete else WAITING_STATUS

    return {
        "schema_version": SCHEMA,
        "status": status,
        **identity,
        "transition_packet_sha256": _canonical_sha256(dict(transition_packet)),
        "deployment_snapshot_sha256": snapshot_sha,
        "warning_clearance_status": warning_status,
        "warning_clearance_sha256": warning_sha,
        "governance_documentation_complete": documentation_complete,
        "fresh_runtime_hard_checks_required": True,
        "state_transition_apply_now": False,
        "transition_rule": (
            "Even when governance documentation is complete, a separate fresh runtime "
            "hard-check receipt bound to this exact identity is still required before any "
            "deployment, stake, promotion, Truth Gate, or OFFICIAL state change."
        ),
        "promotion_authority": False,
        "deployment_change_allowed": False,
        "staking_change_allowed": False,
        "official_change_allowed": False,
    }
