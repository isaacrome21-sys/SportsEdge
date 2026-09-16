"""Read-only warning-clearance contract for MLB MONEYLINE governance.

The module validates documentation required by Promotion Evidence Policy V2.
It cannot edit deployments, change stake, promote a market, or emit an OFFICIAL
bet. Missing or incomplete warning evidence fails closed.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "mlb_moneyline_official_warning_clearance_v1"
STATUS = "OFFICIAL_WARNING_CLEARANCE_PASS"


class MLBMoneylineWarningClearanceError(RuntimeError):
    pass


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _ts(value: Any, field: str) -> str:
    try:
        out = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise MLBMoneylineWarningClearanceError(f"{field}: invalid timestamp") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise MLBMoneylineWarningClearanceError(f"{field}: timezone required")
    return out.astimezone(timezone.utc).isoformat()


def _load_policy(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise MLBMoneylineWarningClearanceError("promotion policy unreadable") from exc
    if not isinstance(value, dict) or value.get("policy_id") != "PROMOTION_EVIDENCE_POLICY_V2":
        raise MLBMoneylineWarningClearanceError("active V2 policy required")
    return value


def validate_warning_clearance(
    receipt: Mapping[str, Any],
    *,
    expected_identity: Mapping[str, str],
    policy_path: str | Path = "config/promotion_evidence_policy_v2.json",
) -> dict[str, Any]:
    if receipt.get("schema_version") != SCHEMA:
        raise MLBMoneylineWarningClearanceError("warning clearance schema mismatch")
    if receipt.get("status") != STATUS:
        raise MLBMoneylineWarningClearanceError("warning clearance not passed")
    for field in (
        "promotion_authority",
        "deployment_change_allowed",
        "staking_change_allowed",
        "official_change_allowed",
    ):
        if receipt.get(field) is not False:
            raise MLBMoneylineWarningClearanceError(
                f"warning clearance must remain non-authoritative: {field}"
            )

    for field in (
        "lane_id",
        "model_artifact_sha256",
        "market_definition_sha256",
        "policy_id",
        "policy_sha256",
    ):
        if str(receipt.get(field) or "") != str(expected_identity.get(field) or ""):
            raise MLBMoneylineWarningClearanceError(f"warning clearance identity mismatch: {field}")

    policy = _load_policy(policy_path)
    universe = policy.get("warning_only_on_probation")
    if not isinstance(universe, list) or not universe:
        raise MLBMoneylineWarningClearanceError("policy warning universe invalid")
    if list(receipt.get("warning_universe") or ()) != universe:
        raise MLBMoneylineWarningClearanceError("warning universe mismatch")

    resolutions = receipt.get("resolutions")
    if not isinstance(resolutions, Mapping) or set(resolutions) != set(universe):
        raise MLBMoneylineWarningClearanceError("every frozen warning requires a resolution")

    normalized: dict[str, dict[str, Any]] = {}
    for warning in universe:
        entry = resolutions.get(warning)
        if not isinstance(entry, Mapping):
            raise MLBMoneylineWarningClearanceError(f"warning resolution invalid: {warning}")
        resolution_status = str(entry.get("status") or "")
        if resolution_status not in {"CLEARED", "SIGNED_OFF"}:
            raise MLBMoneylineWarningClearanceError(f"warning unresolved: {warning}")
        reason = str(entry.get("reason") or "").strip()
        evidence_reference = str(entry.get("evidence_reference") or "").strip()
        if not reason or not evidence_reference:
            raise MLBMoneylineWarningClearanceError(
                f"warning resolution provenance missing: {warning}"
            )
        timestamp = _ts(entry.get("timestamp_utc"), f"{warning}.timestamp_utc")
        actor = str(entry.get("actor") or "").strip()
        if resolution_status == "SIGNED_OFF" and not actor:
            raise MLBMoneylineWarningClearanceError(f"signed-off warning actor missing: {warning}")
        normalized[warning] = {
            "status": resolution_status,
            "actor": actor or None,
            "timestamp_utc": timestamp,
            "reason": reason,
            "evidence_reference": evidence_reference,
        }

    return {
        "schema_version": SCHEMA,
        "status": STATUS,
        **{field: str(receipt.get(field) or "") for field in (
            "lane_id",
            "model_artifact_sha256",
            "market_definition_sha256",
            "policy_id",
            "policy_sha256",
        )},
        "warning_universe": list(universe),
        "resolutions": normalized,
        "receipt_sha256": _canonical_sha256(dict(receipt)),
        "promotion_authority": False,
        "deployment_change_allowed": False,
        "staking_change_allowed": False,
        "official_change_allowed": False,
    }
