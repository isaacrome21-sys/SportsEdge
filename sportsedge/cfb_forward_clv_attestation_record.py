from __future__ import annotations

from datetime import datetime
from typing import Mapping, Sequence

from sportsedge.cfb_forward_clv_settlement import select_attested_close


class AttestationRecordError(ValueError):
    pass


def _dt(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise AttestationRecordError(f"{field}_MISSING")
    text = value.strip().replace("Z", "+00:00")
    try:
        out = datetime.fromisoformat(text)
    except ValueError as exc:
        raise AttestationRecordError(f"{field}_INVALID") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise AttestationRecordError(f"{field}_TIMEZONE_REQUIRED")
    return out


def _optional_dt(value: object, field: str) -> datetime | None:
    if value is None:
        return None
    return _dt(value, field)


def source_stable_from_record(record: Mapping[str, object]) -> bool:
    """Derive, never assume, stabilized-source identity.

    A caller cannot assert source stability directly. Two independently observed,
    hash-bound canonical settlement snapshots must agree and the second read must
    occur after the first. Missing provenance fails closed.
    """
    prior_hash = str(record.get("prior_snapshot_sha256") or "").strip().lower()
    current_hash = str(record.get("current_snapshot_sha256") or "").strip().lower()
    if len(prior_hash) != 64 or len(current_hash) != 64:
        return False
    if prior_hash != current_hash:
        return False
    try:
        prior_at = _dt(record.get("prior_observed_at_utc"), "PRIOR_OBSERVED_AT")
        current_at = _dt(record.get("current_observed_at_utc"), "CURRENT_OBSERVED_AT")
    except AttestationRecordError:
        return False
    return current_at > prior_at


def select_attested_close_from_record(
    candidates: Sequence[Mapping[str, object]],
    *,
    attestation_record: Mapping[str, object],
    stabilization_delay_hours: float,
    max_uncertainty_seconds: float,
    safety_margin_seconds: float,
) -> dict[str, object]:
    """Validate provenance record then invoke the frozen close selector.

    This grants no promotion authority. Missing or ambiguous provenance is
    represented as CLV_MISSING/PENDING by the underlying selector.
    """
    first_play = _optional_dt(attestation_record.get("first_play_utc"), "FIRST_PLAY")
    final_status = _optional_dt(attestation_record.get("final_status_utc"), "FINAL_STATUS")
    sealed_at = _dt(attestation_record.get("sealed_at_utc"), "SEALED_AT")

    precision = attestation_record.get("timestamp_precision_known") is True
    uncertainty_raw = attestation_record.get("timestamp_uncertainty_seconds")
    try:
        uncertainty = None if uncertainty_raw is None else float(uncertainty_raw)
    except (TypeError, ValueError):
        uncertainty = None

    return select_attested_close(
        candidates,
        first_play_ts=first_play,
        final_status_ts=final_status,
        sealed_at_ts=sealed_at,
        timestamp_precision_known=precision,
        timestamp_uncertainty_seconds=uncertainty,
        source_stable_at_seal=source_stable_from_record(attestation_record),
        stabilization_delay_hours=stabilization_delay_hours,
        max_uncertainty_seconds=max_uncertainty_seconds,
        safety_margin_seconds=safety_margin_seconds,
    )
