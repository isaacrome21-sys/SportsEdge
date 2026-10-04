"""Research-only provenance contract for an NFL candidate release proposal.

This module does not activate a candidate, freeze an artifact, create Model_P,
change promotion policy, authorize staking, or create OFFICIAL eligibility.  It
only binds an untouched candidate readout to the identities a later human-
reviewed production-release decision would have to preserve.
"""
from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import Any, Mapping

SCHEMA_VERSION = "SPORTSEDGE_NFL_CANDIDATE_RELEASE_PROPOSAL_V1"
STATUS = "PROPOSED_HUMAN_REVIEW_REQUIRED"
_EXPECTED_CANDIDATE_STATUS = "FIRST_READOUT_DIAGNOSTIC_ONLY"
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ZERO_AUTHORITY_FIELDS = (
    "promotion_eligible",
    "promotion_authority",
    "model_p_authority",
    "official_status_granted",
    "production_registry_consumes_this_artifact",
)


class NFLCandidateReleaseError(ValueError):
    pass


def _identity(value: Any, error: str) -> str:
    resolved = str(value or "").strip()
    if not resolved:
        raise NFLCandidateReleaseError(error)
    return resolved


def _git_sha(value: Any, error: str) -> str:
    resolved = str(value or "").strip().lower()
    if not _GIT_SHA_RE.fullmatch(resolved):
        raise NFLCandidateReleaseError(error)
    return resolved


def _sha256(value: Any, error: str) -> str:
    resolved = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(resolved):
        raise NFLCandidateReleaseError(error)
    return resolved


def canonical_payload_sha256(payload: Mapping[str, Any]) -> str:
    if not isinstance(payload, Mapping):
        raise NFLCandidateReleaseError("NFL_CANDIDATE_RELEASE_EVIDENCE_NOT_OBJECT")
    try:
        raw = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise NFLCandidateReleaseError("NFL_CANDIDATE_RELEASE_EVIDENCE_NOT_CANONICAL") from exc
    return sha256(raw).hexdigest()


def build_candidate_release_proposal(
    candidate_evidence: Mapping[str, Any],
    *,
    candidate_evidence_sha256: str,
    preregistration_sha256: str,
    code_git_sha: str,
    source_manifest_sha256: str,
    proposal_id: str,
) -> dict[str, Any]:
    """Bind a frozen candidate readout into a non-authoritative release proposal.

    The proposal is deliberately one step *before* any production-release
    decision.  It is safe to build while candidate evaluation is still governed
    as research because every authority bit remains false and activation is not
    implemented here.
    """
    if not isinstance(candidate_evidence, Mapping):
        raise NFLCandidateReleaseError("NFL_CANDIDATE_RELEASE_EVIDENCE_NOT_OBJECT")
    if str(candidate_evidence.get("status") or "") != _EXPECTED_CANDIDATE_STATUS:
        raise NFLCandidateReleaseError("NFL_CANDIDATE_RELEASE_READOUT_STATUS_INVALID")
    if candidate_evidence.get("preregistration_locked") is not True:
        raise NFLCandidateReleaseError("NFL_CANDIDATE_RELEASE_PREREGISTRATION_LOCK_REQUIRED")
    if candidate_evidence.get("post_readout_retuning_allowed") is not False:
        raise NFLCandidateReleaseError("NFL_CANDIDATE_RELEASE_POST_READOUT_RETUNING_FORBIDDEN")
    for field in _ZERO_AUTHORITY_FIELDS:
        if candidate_evidence.get(field) is not False:
            raise NFLCandidateReleaseError(f"NFL_CANDIDATE_RELEASE_ZERO_AUTHORITY_REQUIRED:{field}")

    model_id = _identity(
        candidate_evidence.get("model_id"),
        "NFL_CANDIDATE_RELEASE_MODEL_ID_REQUIRED",
    )
    distribution_contract = _identity(
        candidate_evidence.get("distribution_contract"),
        "NFL_CANDIDATE_RELEASE_DISTRIBUTION_CONTRACT_REQUIRED",
    )
    event_contract = _identity(
        candidate_evidence.get("event_contract"),
        "NFL_CANDIDATE_RELEASE_EVENT_CONTRACT_REQUIRED",
    )
    code_sha = _git_sha(code_git_sha, "NFL_CANDIDATE_RELEASE_CODE_SHA_INVALID")
    prereg_sha = _sha256(
        preregistration_sha256,
        "NFL_CANDIDATE_RELEASE_PREREGISTRATION_SHA256_INVALID",
    )
    source_sha = _sha256(
        source_manifest_sha256,
        "NFL_CANDIDATE_RELEASE_SOURCE_MANIFEST_SHA256_INVALID",
    )
    evidence_source_sha = _sha256(
        candidate_evidence.get("source_manifest_sha256"),
        "NFL_CANDIDATE_RELEASE_EVIDENCE_SOURCE_MANIFEST_SHA256_INVALID",
    )
    if evidence_source_sha != source_sha:
        raise NFLCandidateReleaseError("NFL_CANDIDATE_RELEASE_SOURCE_MANIFEST_MISMATCH")

    expected_evidence_sha = _sha256(
        candidate_evidence_sha256,
        "NFL_CANDIDATE_RELEASE_EVIDENCE_SHA256_INVALID",
    )
    actual_evidence_sha = canonical_payload_sha256(candidate_evidence)
    if actual_evidence_sha != expected_evidence_sha:
        raise NFLCandidateReleaseError("NFL_CANDIDATE_RELEASE_EVIDENCE_SHA256_MISMATCH")

    proposal = _identity(proposal_id, "NFL_CANDIDATE_RELEASE_PROPOSAL_ID_REQUIRED")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "sport": "nfl",
        "proposal_id": proposal,
        "candidate": {
            "model_id": model_id,
            "distribution_contract": distribution_contract,
            "event_contract": event_contract,
            "code_git_sha": code_sha,
            "source_manifest_sha256": source_sha,
            "preregistration_sha256": prereg_sha,
            "untouched_readout_sha256": actual_evidence_sha,
            "readout_status": _EXPECTED_CANDIDATE_STATUS,
        },
        "human_review_required": True,
        "selected_for_production": False,
        "production_release_identity": None,
        "frozen_artifact_binding": False,
        "forward_clv_must_start_after_freeze": True,
        "historical_or_backfilled_clv_allowed": False,
        "activation_implemented": False,
        "promotion_authority": False,
        "model_p_authority": False,
        "staking_authority": False,
        "official_authority": False,
    }


def validate_non_authoritative_release_proposal(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed if a proposal has been mutated to imply production authority."""
    if not isinstance(payload, Mapping):
        raise NFLCandidateReleaseError("NFL_CANDIDATE_RELEASE_PROPOSAL_NOT_OBJECT")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise NFLCandidateReleaseError("NFL_CANDIDATE_RELEASE_PROPOSAL_SCHEMA_INVALID")
    if payload.get("status") != STATUS:
        raise NFLCandidateReleaseError("NFL_CANDIDATE_RELEASE_PROPOSAL_STATUS_INVALID")
    if str(payload.get("sport") or "").lower() != "nfl":
        raise NFLCandidateReleaseError("NFL_CANDIDATE_RELEASE_PROPOSAL_SPORT_INVALID")
    if payload.get("human_review_required") is not True:
        raise NFLCandidateReleaseError("NFL_CANDIDATE_RELEASE_HUMAN_REVIEW_REQUIRED")
    if payload.get("selected_for_production") is not False:
        raise NFLCandidateReleaseError("NFL_CANDIDATE_RELEASE_SELECTION_NOT_ALLOWED")
    if payload.get("production_release_identity") is not None:
        raise NFLCandidateReleaseError("NFL_CANDIDATE_RELEASE_PRODUCTION_IDENTITY_NOT_ALLOWED")
    if payload.get("frozen_artifact_binding") is not False:
        raise NFLCandidateReleaseError("NFL_CANDIDATE_RELEASE_FREEZE_NOT_ALLOWED")
    if payload.get("forward_clv_must_start_after_freeze") is not True:
        raise NFLCandidateReleaseError("NFL_CANDIDATE_RELEASE_FORWARD_CLV_CONTRACT_INVALID")
    if payload.get("historical_or_backfilled_clv_allowed") is not False:
        raise NFLCandidateReleaseError("NFL_CANDIDATE_RELEASE_BACKFILL_FORBIDDEN")
    if payload.get("activation_implemented") is not False:
        raise NFLCandidateReleaseError("NFL_CANDIDATE_RELEASE_ACTIVATION_NOT_ALLOWED")
    for field in ("promotion_authority", "model_p_authority", "staking_authority", "official_authority"):
        if payload.get(field) is not False:
            raise NFLCandidateReleaseError(f"NFL_CANDIDATE_RELEASE_AUTHORITY_NOT_ALLOWED:{field}")

    candidate = payload.get("candidate")
    if not isinstance(candidate, Mapping):
        raise NFLCandidateReleaseError("NFL_CANDIDATE_RELEASE_CANDIDATE_IDENTITY_REQUIRED")
    _identity(candidate.get("model_id"), "NFL_CANDIDATE_RELEASE_MODEL_ID_REQUIRED")
    _identity(
        candidate.get("distribution_contract"),
        "NFL_CANDIDATE_RELEASE_DISTRIBUTION_CONTRACT_REQUIRED",
    )
    _identity(candidate.get("event_contract"), "NFL_CANDIDATE_RELEASE_EVENT_CONTRACT_REQUIRED")
    _git_sha(candidate.get("code_git_sha"), "NFL_CANDIDATE_RELEASE_CODE_SHA_INVALID")
    _sha256(
        candidate.get("source_manifest_sha256"),
        "NFL_CANDIDATE_RELEASE_SOURCE_MANIFEST_SHA256_INVALID",
    )
    _sha256(
        candidate.get("preregistration_sha256"),
        "NFL_CANDIDATE_RELEASE_PREREGISTRATION_SHA256_INVALID",
    )
    _sha256(
        candidate.get("untouched_readout_sha256"),
        "NFL_CANDIDATE_RELEASE_EVIDENCE_SHA256_INVALID",
    )
    if candidate.get("readout_status") != _EXPECTED_CANDIDATE_STATUS:
        raise NFLCandidateReleaseError("NFL_CANDIDATE_RELEASE_READOUT_STATUS_INVALID")
    return dict(payload)
