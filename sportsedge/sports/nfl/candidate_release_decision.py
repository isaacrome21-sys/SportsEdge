"""Zero-authority human-reviewed NFL candidate release decision contract.

This module is the governance handoff between a validated candidate proposal and
any later production-artifact build. It does not serialize a production model,
freeze an artifact, start CLV, create Model_P, promote a market, stake, or grant
OFFICIAL authority.
"""
from __future__ import annotations

from typing import Any, Mapping

from sportsedge.sports.nfl.candidate_release import (
    NFLCandidateReleaseError,
    canonical_payload_sha256,
    validate_non_authoritative_release_proposal,
)
from sportsedge.sports.nfl.m2 import PRODUCTION_NFL_M2_MODEL_ID

SCHEMA_VERSION = "SPORTSEDGE_NFL_CANDIDATE_RELEASE_DECISION_V1"
STATUS = "SELECTED_FOR_RELEASE_BUILD_ZERO_AUTHORITY"


class NFLCandidateReleaseDecisionError(ValueError):
    pass


def _identity(value: Any, code: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise NFLCandidateReleaseDecisionError(code)
    return text


def _sha256(value: Any, code: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise NFLCandidateReleaseDecisionError(code)
    return text


def _candidate_from_proposal(proposal: Mapping[str, Any]) -> dict[str, Any]:
    candidate = proposal.get("candidate")
    if not isinstance(candidate, Mapping):
        raise NFLCandidateReleaseDecisionError("NFL_RELEASE_DECISION_CANDIDATE_REQUIRED")
    row = dict(candidate)
    model_id = _identity(row.get("model_id"), "NFL_RELEASE_DECISION_MODEL_ID_REQUIRED")
    if model_id == PRODUCTION_NFL_M2_MODEL_ID:
        raise NFLCandidateReleaseDecisionError("NFL_RELEASE_DECISION_LEGACY_M2_RELABEL_FORBIDDEN")
    for key in ("distribution_contract", "event_contract"):
        _identity(row.get(key), f"NFL_RELEASE_DECISION_{key.upper()}_REQUIRED")
    code_sha = str(row.get("code_git_sha") or "").strip().lower()
    if len(code_sha) != 40 or any(ch not in "0123456789abcdef" for ch in code_sha):
        raise NFLCandidateReleaseDecisionError("NFL_RELEASE_DECISION_CODE_SHA_INVALID")
    for key in ("source_manifest_sha256", "preregistration_sha256", "untouched_readout_sha256"):
        _sha256(row.get(key), f"NFL_RELEASE_DECISION_{key.upper()}_INVALID")
    if row.get("readout_status") != "FIRST_READOUT_DIAGNOSTIC_ONLY":
        raise NFLCandidateReleaseDecisionError("NFL_RELEASE_DECISION_READOUT_STATUS_INVALID")
    return row


def build_candidate_release_decision(
    proposal: Mapping[str, Any],
    *,
    proposal_sha256: str,
    reviewer: str,
    review_ticket: str,
    production_release_id: str,
) -> dict[str, Any]:
    try:
        validated = validate_non_authoritative_release_proposal(proposal)
    except NFLCandidateReleaseError as exc:
        raise NFLCandidateReleaseDecisionError(str(exc)) from exc

    expected = _sha256(proposal_sha256, "NFL_RELEASE_DECISION_PROPOSAL_SHA256_INVALID")
    actual = canonical_payload_sha256(validated)
    if actual != expected:
        raise NFLCandidateReleaseDecisionError("NFL_RELEASE_DECISION_PROPOSAL_SHA256_MISMATCH")

    candidate = _candidate_from_proposal(validated)
    release_id = _identity(production_release_id, "NFL_RELEASE_DECISION_RELEASE_ID_REQUIRED")
    if release_id in {candidate["model_id"], PRODUCTION_NFL_M2_MODEL_ID}:
        raise NFLCandidateReleaseDecisionError("NFL_RELEASE_DECISION_RELEASE_ID_NOT_VERSIONED")
    review_by = _identity(reviewer, "NFL_RELEASE_DECISION_REVIEWER_REQUIRED")
    ticket = _identity(review_ticket, "NFL_RELEASE_DECISION_REVIEW_TICKET_REQUIRED")

    identity = {
        "release_id": release_id,
        "source_candidate_model_id": candidate["model_id"],
        "distribution_contract": candidate["distribution_contract"],
        "event_contract": candidate["event_contract"],
        "code_git_sha": candidate["code_git_sha"],
        "source_manifest_sha256": candidate["source_manifest_sha256"],
        "preregistration_sha256": candidate["preregistration_sha256"],
        "untouched_readout_sha256": candidate["untouched_readout_sha256"],
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "sport": "nfl",
        "proposal_sha256": actual,
        "review": {"reviewer": review_by, "ticket": ticket},
        "candidate": candidate,
        "selected_for_production": True,
        "production_release_identity": identity,
        "release_artifact_built": False,
        "frozen_artifact_binding": False,
        "activation_implemented": False,
        "forward_clv_must_start_after_freeze": True,
        "historical_or_backfilled_clv_allowed": False,
        "promotion_authority": False,
        "model_p_authority": False,
        "staking_authority": False,
        "official_authority": False,
    }


def validate_candidate_release_decision(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise NFLCandidateReleaseDecisionError("NFL_RELEASE_DECISION_NOT_OBJECT")
    row = dict(payload)
    if row.get("schema_version") != SCHEMA_VERSION or row.get("status") != STATUS:
        raise NFLCandidateReleaseDecisionError("NFL_RELEASE_DECISION_SCHEMA_OR_STATUS_INVALID")
    if str(row.get("sport") or "").lower() != "nfl":
        raise NFLCandidateReleaseDecisionError("NFL_RELEASE_DECISION_SPORT_INVALID")
    _sha256(row.get("proposal_sha256"), "NFL_RELEASE_DECISION_PROPOSAL_SHA256_INVALID")
    review = row.get("review")
    if not isinstance(review, Mapping):
        raise NFLCandidateReleaseDecisionError("NFL_RELEASE_DECISION_REVIEW_REQUIRED")
    _identity(review.get("reviewer"), "NFL_RELEASE_DECISION_REVIEWER_REQUIRED")
    _identity(review.get("ticket"), "NFL_RELEASE_DECISION_REVIEW_TICKET_REQUIRED")
    candidate = _candidate_from_proposal({"candidate": row.get("candidate")})
    if row.get("selected_for_production") is not True:
        raise NFLCandidateReleaseDecisionError("NFL_RELEASE_DECISION_SELECTION_REQUIRED")
    identity = row.get("production_release_identity")
    if not isinstance(identity, Mapping):
        raise NFLCandidateReleaseDecisionError("NFL_RELEASE_DECISION_PRODUCTION_IDENTITY_REQUIRED")
    release_id = _identity(identity.get("release_id"), "NFL_RELEASE_DECISION_RELEASE_ID_REQUIRED")
    if release_id in {candidate["model_id"], PRODUCTION_NFL_M2_MODEL_ID}:
        raise NFLCandidateReleaseDecisionError("NFL_RELEASE_DECISION_RELEASE_ID_NOT_VERSIONED")
    expected_identity = {
        "release_id": release_id,
        "source_candidate_model_id": candidate["model_id"],
        "distribution_contract": candidate["distribution_contract"],
        "event_contract": candidate["event_contract"],
        "code_git_sha": candidate["code_git_sha"],
        "source_manifest_sha256": candidate["source_manifest_sha256"],
        "preregistration_sha256": candidate["preregistration_sha256"],
        "untouched_readout_sha256": candidate["untouched_readout_sha256"],
    }
    if dict(identity) != expected_identity:
        raise NFLCandidateReleaseDecisionError("NFL_RELEASE_DECISION_IDENTITY_BINDING_MISMATCH")
    for field in ("release_artifact_built", "frozen_artifact_binding", "activation_implemented",
                  "historical_or_backfilled_clv_allowed", "promotion_authority",
                  "model_p_authority", "staking_authority", "official_authority"):
        if row.get(field) is not False:
            raise NFLCandidateReleaseDecisionError(f"NFL_RELEASE_DECISION_ZERO_AUTHORITY_REQUIRED:{field}")
    if row.get("forward_clv_must_start_after_freeze") is not True:
        raise NFLCandidateReleaseDecisionError("NFL_RELEASE_DECISION_FORWARD_CLV_CONTRACT_INVALID")
    return row
