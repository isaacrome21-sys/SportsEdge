"""Fail-closed transition packet preflight for governed MLB MONEYLINE authority.

This module does not edit deployments, staking, Truth Gate state, or OFFICIAL state.
It only converts an already-passing terminal readiness receipt into a signed-by-content
transition candidate packet that still requires fresh runtime hard-check and warning
clearance receipts before any separate governed state change may occur.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

SCHEMA = "mlb_moneyline_transition_packet_v1"
READINESS_SCHEMA = "mlb_moneyline_authority_readiness_v1"
READY_STATUS = "TERMINAL_EVIDENCE_PREREQUISITES_OBSERVED_TRANSITION_STILL_REQUIRED"


class MLBMoneylineTransitionPacketError(RuntimeError):
    pass


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _load(path: str | Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise MLBMoneylineTransitionPacketError(f"{label} unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise MLBMoneylineTransitionPacketError(f"{label} must be an object")
    return value


def build_transition_packet(
    *,
    readiness: Mapping[str, Any],
    deployments: Mapping[str, Any],
) -> dict[str, Any]:
    if readiness.get("schema_version") != READINESS_SCHEMA:
        raise MLBMoneylineTransitionPacketError("readiness schema mismatch")

    authority_fields = (
        "promotion_authority",
        "deployment_change_allowed",
        "staking_change_allowed",
        "official_change_allowed",
    )
    if any(readiness.get(field) is not False for field in authority_fields):
        raise MLBMoneylineTransitionPacketError("readiness receipt must remain non-authoritative")

    checks = readiness.get("checks")
    if not isinstance(checks, Mapping) or not checks:
        raise MLBMoneylineTransitionPacketError("readiness checks unavailable")

    terminal_ready = bool(
        readiness.get("status") == READY_STATUS
        and readiness.get("all_terminal_evidence_prerequisites_observed") is True
        and all(value is True for value in checks.values())
    )
    if not terminal_ready:
        raise MLBMoneylineTransitionPacketError("terminal evidence prerequisites not observed")

    markets = deployments.get("markets")
    if not isinstance(markets, Mapping):
        raise MLBMoneylineTransitionPacketError("deployments markets unavailable")
    moneyline = markets.get("MONEYLINE")
    if not isinstance(moneyline, Mapping):
        raise MLBMoneylineTransitionPacketError("MONEYLINE deployment unavailable")
    if moneyline.get("eligible") is not False:
        raise MLBMoneylineTransitionPacketError("MONEYLINE must remain fail closed before transition")

    snapshot = readiness.get("deployment_snapshot")
    if not isinstance(snapshot, Mapping) or dict(snapshot) != dict(moneyline):
        raise MLBMoneylineTransitionPacketError("deployment snapshot drift")

    identity = {
        "lane_id": str(readiness.get("lane_id") or ""),
        "model_artifact_sha256": str(readiness.get("model_artifact_sha256") or ""),
        "market_definition_sha256": str(readiness.get("market_definition_sha256") or ""),
        "policy_id": str(readiness.get("policy_id") or ""),
        "policy_sha256": str(readiness.get("policy_sha256") or ""),
    }
    if not identity["lane_id"] or not identity["policy_id"]:
        raise MLBMoneylineTransitionPacketError("transition identity incomplete")
    for field in ("model_artifact_sha256", "market_definition_sha256", "policy_sha256"):
        value = identity[field]
        if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise MLBMoneylineTransitionPacketError(f"invalid identity digest: {field}")

    readiness_payload = dict(readiness)
    packet_basis = {
        "identity": identity,
        "readiness_sha256": _canonical_sha256(readiness_payload),
        "deployment_snapshot_sha256": _canonical_sha256(dict(moneyline)),
    }

    return {
        "schema_version": SCHEMA,
        "status": "READY_FOR_FRESH_RUNTIME_AND_WARNING_CLEARANCE",
        **identity,
        **packet_basis,
        "required_transition_receipts": [
            "FRESH_RUNTIME_HARD_CHECKS_PASS",
            "OFFICIAL_WARNING_CLEARANCE_PASS",
        ],
        "proposed_state_change": {
            "market": "MONEYLINE",
            "from_eligible": False,
            "to_eligible": True,
            "apply_now": False,
        },
        "transition_rule": (
            "This packet is a non-authoritative candidate only. A separate governed transition "
            "must verify fresh runtime hard checks and official warning clearance against the "
            "same frozen identity before changing deployment, stake, promotion, or OFFICIAL state."
        ),
        "promotion_authority": False,
        "deployment_change_allowed": False,
        "staking_change_allowed": False,
        "official_change_allowed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readiness", default="artifacts/mlb_moneyline_authority_readiness_report.json")
    parser.add_argument("--deployments", default="config/deployments.json")
    parser.add_argument("--report", default="artifacts/mlb_moneyline_transition_packet.json")
    args = parser.parse_args(argv)

    try:
        readiness = _load(args.readiness, "readiness report")
        deployments = _load(args.deployments, "deployments")
        report = build_transition_packet(readiness=readiness, deployments=deployments)
        rc = 0
    except Exception as exc:
        report = {
            "schema_version": SCHEMA,
            "status": "BLOCKED_TRANSITION_PACKET",
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
