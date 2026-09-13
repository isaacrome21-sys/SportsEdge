from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Mapping, Sequence

from sportsedge.cfb_forward_clv_attestation_record import select_attested_close_from_record


class CFBForwardRuntimeError(ValueError):
    pass


def _sha256_json(payload: Mapping[str, object]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _parse_ts(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise CFBForwardRuntimeError("CAPTURE_TIMESTAMP_MISSING")
    text = value.strip().replace("Z", "+00:00")
    try:
        out = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CFBForwardRuntimeError("CAPTURE_TIMESTAMP_INVALID") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise CFBForwardRuntimeError("CAPTURE_TIMESTAMP_TIMEZONE_REQUIRED")
    return out


def _frozen_attestation_parameters(policy: Mapping[str, object]) -> tuple[float, float, float]:
    if policy.get("policy_id") != "CFB_FORWARD_CLV_POLICY_V1" or policy.get("status") != "FROZEN":
        raise CFBForwardRuntimeError("CFB_FORWARD_POLICY_NOT_FROZEN")
    try:
        close = policy["capture_schedule"]  # type: ignore[index]
        close = close["close"]  # type: ignore[index]
        att = close["actual_start_attestation"]  # type: ignore[index]
        delay = float(att["stabilization_delay_hours"])  # type: ignore[index]
        max_uncertainty = float(att["max_acceptable_timestamp_uncertainty_seconds"])  # type: ignore[index]
        safety_margin = float(att["safety_margin_seconds"])  # type: ignore[index]
    except (KeyError, TypeError, ValueError) as exc:
        raise CFBForwardRuntimeError("CFB_FORWARD_ATTESTATION_POLICY_MALFORMED") from exc
    if delay != 12.0 or max_uncertainty != 30.0 or safety_margin != 30.0:
        raise CFBForwardRuntimeError("CFB_FORWARD_ATTESTATION_POLICY_UNEXPECTED")
    return delay, max_uncertainty, safety_margin


def settle_close_group(
    raw_records: Sequence[Mapping[str, object]],
    *,
    attestation_record: Mapping[str, object],
    policy: Mapping[str, object],
) -> dict[str, object]:
    """Settle one game's raw close snapshots under the frozen CFB policy.

    Raw snapshots never become evidence by themselves. Selection is delegated
    exclusively to the hash-bound attestation-record path. Missing/ambiguous
    provenance therefore cannot be bypassed by a simple quote<first-play check.
    """
    delay, max_uncertainty, safety_margin = _frozen_attestation_parameters(policy)
    if not raw_records:
        return {
            "status": "CLV_MISSING",
            "reason": "NO_RAW_CLOSE_CANDIDATES",
            "promotion_authority": False,
            "selected_candidate_id": None,
            "raw_snapshot_count": 0,
        }

    espn_ids = {str(r.get("espn_event_id") or "") for r in raw_records}
    if "" in espn_ids or len(espn_ids) != 1:
        raise CFBForwardRuntimeError("RAW_CLOSE_EVENT_ID_MISMATCH")
    expected_espn_id = next(iter(espn_ids))
    if str(attestation_record.get("espn_event_id") or "") != expected_espn_id:
        raise CFBForwardRuntimeError("ATTESTATION_EVENT_ID_MISMATCH")

    policy_ids = {str(r.get("policy_id") or "") for r in raw_records}
    policy_versions = {str(r.get("policy_version") or "") for r in raw_records}
    if policy_ids != {str(policy.get("policy_id"))} or policy_versions != {str(policy.get("version"))}:
        raise CFBForwardRuntimeError("RAW_CLOSE_POLICY_IDENTITY_MISMATCH")

    candidates = []
    for record in raw_records:
        captured = _parse_ts(record.get("captured_at_utc"))
        candidates.append({
            "candidate_id": _sha256_json(record),
            "quote_ts": captured,
        })

    selected = select_attested_close_from_record(
        candidates,
        attestation_record=attestation_record,
        stabilization_delay_hours=delay,
        max_uncertainty_seconds=max_uncertainty,
        safety_margin_seconds=safety_margin,
    )
    return {
        **selected,
        "raw_snapshot_count": len(raw_records),
        "espn_event_id": expected_espn_id,
        "policy_id": policy.get("policy_id"),
        "policy_version": policy.get("version"),
        "attestation_record_sha256": _sha256_json(attestation_record),
    }
