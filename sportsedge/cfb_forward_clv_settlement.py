from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Mapping, Sequence

from sportsedge.cfb_forward_clv_governance import evaluate_first_play_attestation


def select_attested_close(
    candidates: Sequence[Mapping[str, object]],
    *,
    first_play_ts: datetime | None,
    final_status_ts: datetime | None,
    sealed_at_ts: datetime,
    timestamp_precision_known: bool,
    timestamp_uncertainty_seconds: float | None,
    source_stable_at_seal: bool,
    stabilization_delay_hours: float,
    max_uncertainty_seconds: float,
    safety_margin_seconds: float,
) -> dict[str, object]:
    """Deterministically select the latest frozen-policy-valid close candidate.

    This function has no promotion authority. Every candidate is classified by
    the frozen first-play attestation evaluator. Missing/ambiguous provenance
    cannot be inferred. If no candidate survives, the row is retained as
    CLV_MISSING.
    """
    evaluated: list[dict[str, object]] = []
    valid: list[tuple[datetime, Mapping[str, object], dict[str, object]]] = []

    for candidate in candidates:
        quote_ts = candidate.get("quote_ts")
        if not isinstance(quote_ts, datetime):
            evaluated.append({
                "candidate_id": candidate.get("candidate_id"),
                "status": "INVALID_ATTESTATION_UNVERIFIED",
                "reason": "QUOTE_TIMESTAMP_MISSING_OR_INVALID",
            })
            continue
        decision = evaluate_first_play_attestation(
            quote_ts=quote_ts,
            first_play_ts=first_play_ts,
            final_status_ts=final_status_ts,
            sealed_at_ts=sealed_at_ts,
            timestamp_precision_known=timestamp_precision_known,
            timestamp_uncertainty_seconds=timestamp_uncertainty_seconds,
            source_stable_at_seal=source_stable_at_seal,
            stabilization_delay_hours=stabilization_delay_hours,
            max_uncertainty_seconds=max_uncertainty_seconds,
            safety_margin_seconds=safety_margin_seconds,
        )
        item = {"candidate_id": candidate.get("candidate_id"), **asdict(decision)}
        evaluated.append(item)
        if decision.status == "VALID_ATTESTED_PRE_START":
            valid.append((quote_ts, candidate, item))

    if valid:
        quote_ts, candidate, attestation = max(valid, key=lambda row: row[0])
        return {
            "promotion_authority": False,
            "status": "SELECTED",
            "selected_candidate_id": candidate.get("candidate_id"),
            "selected_quote_ts": quote_ts,
            "attestation": attestation,
            "candidate_results": evaluated,
        }

    reasons = [str(item.get("reason") or "") for item in evaluated]
    pending = "STABILIZATION_DELAY_NOT_MET" in reasons
    return {
        "promotion_authority": False,
        "status": "PENDING_STABILIZATION" if pending else "CLV_MISSING",
        "reason": "NO_FROZEN_POLICY_VALID_CLOSE_CANDIDATE",
        "selected_candidate_id": None,
        "candidate_results": evaluated,
    }
