from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


class NFLCandidateAuthorityError(ValueError):
    pass


NON_AUTHORIZED_STATES = frozenset({
    "UNTESTED",
    "RESEARCH_ONLY",
    "PAPER",
    "REJECTED",
    "FAILED",
    "REJECTED_FROZEN_ATTEMPT",
    "BLOCKED_MATH",
    "BLOCKED_CALIBRATION",
    "BLOCKED_PREDICTIVE",
})

AUTHORIZED_STATE = "PROMOTED"
RESERVED_2026_ALLOWED_USES = frozenset({
    "FIRST_WRITE_PREDICTION_CAPTURE",
    "OBJECTIVE_OUTCOME_CAPTURE",
    "FORWARD_CLV_CAPTURE",
    "PREDECLARED_FIXED_CHECKPOINT_EVALUATION",
})


@dataclass(frozen=True)
class CandidateAuthorityDecision:
    candidate_status: str
    run_it_model_authorized: bool
    paper_only: bool
    stake_units: float | None
    model_p_authority: bool
    staking_authority: bool
    reason: str


def candidate_authority(candidate: Mapping[str, Any]) -> CandidateAuthorityDecision:
    status = str(candidate.get("status") or "UNTESTED").strip().upper()
    promotion_authority = candidate.get("promotion_authority") is True
    model_p_authority = candidate.get("model_p_authority") is True
    frozen_artifact_binding = candidate.get("frozen_artifact_binding") is True
    truth_gate_authorized = candidate.get("truth_gate_authorized") is True

    if status in NON_AUTHORIZED_STATES:
        return CandidateAuthorityDecision(
            candidate_status=status,
            run_it_model_authorized=False,
            paper_only=True,
            stake_units=0.0,
            model_p_authority=False,
            staking_authority=False,
            reason=f"NFL_CANDIDATE_NOT_AUTHORIZED:{status}",
        )

    if status != AUTHORIZED_STATE:
        return CandidateAuthorityDecision(
            candidate_status=status,
            run_it_model_authorized=False,
            paper_only=True,
            stake_units=0.0,
            model_p_authority=False,
            staking_authority=False,
            reason=f"NFL_CANDIDATE_STATUS_NOT_PROMOTED:{status}",
        )

    required = {
        "promotion_authority": promotion_authority,
        "model_p_authority": model_p_authority,
        "frozen_artifact_binding": frozen_artifact_binding,
        "truth_gate_authorized": truth_gate_authorized,
    }
    missing = [name for name, ok in required.items() if not ok]
    if missing:
        return CandidateAuthorityDecision(
            candidate_status=status,
            run_it_model_authorized=False,
            paper_only=True,
            stake_units=0.0,
            model_p_authority=False,
            staking_authority=False,
            reason="NFL_PROMOTED_CANDIDATE_AUTHORITY_INCOMPLETE:" + ",".join(missing),
        )

    # Promotion authorizes the model only. Stake size belongs to a separate,
    # current-price edge/risk/Kelly decision and must never be manufactured here.
    return CandidateAuthorityDecision(
        candidate_status=status,
        run_it_model_authorized=True,
        paper_only=False,
        stake_units=None,
        model_p_authority=True,
        staking_authority=False,
        reason="NFL_CANDIDATE_MODEL_AUTHORIZED_STAKING_SEPARATE",
    )


def require_run_it_model_authority(candidate: Mapping[str, Any]) -> CandidateAuthorityDecision:
    decision = candidate_authority(candidate)
    if not decision.run_it_model_authorized:
        raise NFLCandidateAuthorityError(decision.reason)
    return decision


def require_reserved_2026_use(purpose: str) -> str:
    normalized = str(purpose or "").strip().upper()
    if normalized not in RESERVED_2026_ALLOWED_USES:
        raise NFLCandidateAuthorityError(f"NFL_2026_RESERVED_STREAM_USE_BLOCKED:{normalized or 'EMPTY'}")
    return normalized
