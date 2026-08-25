"""Final NFL promotion bridge requiring external forward-CLV authenticity.

The lower-level registry validates evidence semantics.  This module is the
production bridge: it additionally requires an attestation created by the
scheduled forward collection workflow and binds that attestation to the exact
CLV payload before the registry is allowed to evaluate DEPLOYED.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
import re
from typing import Any

from sportsedge.core.promotion.football_registry import build_nfl_promotion_registry
from sportsedge.core.validation.nfl_forward_clv_attestation import canonical_clv_payload_sha256
from sportsedge.sports.nfl.m2 import NFL_M2_FEATURE_CONTRACT, PRODUCTION_NFL_M2_MODEL_ID

_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_EXPECTED_WORKFLOW = "football-nfl-forward-clv-collection"
_EXPECTED_CONTRACT = "NFL_FORWARD_CLV_COLLECTION_V1"


def _mapping(value: Any, error: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(error)
    return value


def _hash(value: Any, error: str) -> str:
    raw = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(raw):
        raise ValueError(error)
    return raw


def _git_sha(value: Any, error: str) -> str:
    raw = str(value or "").strip().lower()
    if not _GIT_SHA_RE.fullmatch(raw):
        raise ValueError(error)
    return raw


def _count(value: Any, error: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(error)
    return value


def verify_nfl_forward_clv_attestation(
    clv_evidence: Mapping[str, Any],
    clv_attestation: Mapping[str, Any] | None,
    *,
    expected_code_sha: str,
) -> dict[str, Any]:
    attestation = _mapping(clv_attestation, "NFL_FORWARD_CLV_ATTESTATION_REQUIRED")
    if int(attestation.get("schema_version", 0)) != 1:
        raise ValueError("NFL_FORWARD_CLV_ATTESTATION_SCHEMA_INVALID")
    if attestation.get("collector_contract") != _EXPECTED_CONTRACT:
        raise ValueError("NFL_FORWARD_CLV_COLLECTOR_CONTRACT_INVALID")
    if attestation.get("workflow_name") != _EXPECTED_WORKFLOW:
        raise ValueError("NFL_FORWARD_CLV_WORKFLOW_NAME_MISMATCH")
    if str(attestation.get("workflow_conclusion") or "").strip().lower() != "success":
        raise ValueError("NFL_FORWARD_CLV_WORKFLOW_NOT_SUCCESSFUL")
    if str(attestation.get("workflow_event") or "").strip().lower() != "schedule":
        raise ValueError("NFL_FORWARD_CLV_WORKFLOW_EVENT_INVALID")
    if str(attestation.get("workflow_head_branch") or "").strip() != "main":
        raise ValueError("NFL_FORWARD_CLV_HEAD_BRANCH_INVALID")
    try:
        run_id = int(attestation.get("workflow_run_id"))
    except (TypeError, ValueError) as exc:
        raise ValueError("NFL_FORWARD_CLV_WORKFLOW_RUN_ID_INVALID") from exc
    if run_id <= 0:
        raise ValueError("NFL_FORWARD_CLV_WORKFLOW_RUN_ID_INVALID")

    code_sha = _git_sha(attestation.get("git_sha"), "NFL_FORWARD_CLV_CODE_SHA_INVALID")
    if code_sha != _git_sha(expected_code_sha, "NFL_FORWARD_CLV_EXPECTED_CODE_SHA_INVALID"):
        raise ValueError("NFL_FORWARD_CLV_CODE_SHA_MISMATCH")
    if clv_evidence.get("model_id") != PRODUCTION_NFL_M2_MODEL_ID or attestation.get("model_id") != PRODUCTION_NFL_M2_MODEL_ID:
        raise ValueError("NFL_FORWARD_CLV_MODEL_ID_MISMATCH")
    if clv_evidence.get("feature_contract") != NFL_M2_FEATURE_CONTRACT or attestation.get("feature_contract") != NFL_M2_FEATURE_CONTRACT:
        raise ValueError("NFL_FORWARD_CLV_FEATURE_CONTRACT_MISMATCH")

    decision_hash = _hash(clv_evidence.get("decision_log_sha256"), "NFL_FORWARD_CLV_DECISION_LOG_SHA256_INVALID")
    close_hash = _hash(clv_evidence.get("close_log_sha256"), "NFL_FORWARD_CLV_CLOSE_LOG_SHA256_INVALID")
    if _hash(attestation.get("decision_log_sha256"), "NFL_FORWARD_CLV_ATTESTED_DECISION_LOG_SHA256_INVALID") != decision_hash:
        raise ValueError("NFL_FORWARD_CLV_DECISION_LOG_MISMATCH")
    if _hash(attestation.get("close_log_sha256"), "NFL_FORWARD_CLV_ATTESTED_CLOSE_LOG_SHA256_INVALID") != close_hash:
        raise ValueError("NFL_FORWARD_CLV_CLOSE_LOG_MISMATCH")

    expected_payload = canonical_clv_payload_sha256(clv_evidence)
    if _hash(attestation.get("clv_payload_sha256"), "NFL_FORWARD_CLV_PAYLOAD_SHA256_INVALID") != expected_payload:
        raise ValueError("NFL_FORWARD_CLV_PAYLOAD_MISMATCH")

    decision_count = _count(clv_evidence.get("decision_count"), "NFL_FORWARD_CLV_DECISION_COUNT_INVALID")
    close_count = _count(clv_evidence.get("close_count"), "NFL_FORWARD_CLV_CLOSE_COUNT_INVALID")
    unique_count = _count(clv_evidence.get("unique_observation_count"), "NFL_FORWARD_CLV_UNIQUE_COUNT_INVALID")
    if _count(attestation.get("decision_count"), "NFL_FORWARD_CLV_ATTESTED_DECISION_COUNT_INVALID") != decision_count:
        raise ValueError("NFL_FORWARD_CLV_DECISION_COUNT_MISMATCH")
    if _count(attestation.get("close_count"), "NFL_FORWARD_CLV_ATTESTED_CLOSE_COUNT_INVALID") != close_count:
        raise ValueError("NFL_FORWARD_CLV_CLOSE_COUNT_MISMATCH")
    if _count(attestation.get("unique_observation_count"), "NFL_FORWARD_CLV_ATTESTED_UNIQUE_COUNT_INVALID") != unique_count:
        raise ValueError("NFL_FORWARD_CLV_UNIQUE_COUNT_MISMATCH")
    try:
        verified = int(attestation.get("verified_artifact_count"))
    except (TypeError, ValueError) as exc:
        raise ValueError("NFL_FORWARD_CLV_VERIFIED_ARTIFACT_COUNT_INVALID") from exc
    if verified < 3:
        raise ValueError("NFL_FORWARD_CLV_VERIFIED_ARTIFACT_COUNT_INVALID")

    return {
        "schema_version": 1,
        "collector_contract": _EXPECTED_CONTRACT,
        "workflow_name": _EXPECTED_WORKFLOW,
        "workflow_conclusion": "success",
        "workflow_event": "schedule",
        "workflow_head_branch": "main",
        "workflow_run_id": run_id,
        "git_sha": code_sha,
        "model_id": PRODUCTION_NFL_M2_MODEL_ID,
        "feature_contract": NFL_M2_FEATURE_CONTRACT,
        "decision_log_sha256": decision_hash,
        "close_log_sha256": close_hash,
        "clv_payload_sha256": expected_payload,
        "decision_count": decision_count,
        "close_count": close_count,
        "unique_observation_count": unique_count,
        "verified_artifact_count": verified,
    }


def build_externally_attested_nfl_registry(
    math_artifact: Mapping[str, Any],
    historical_evidence: Mapping[str, Any],
    *,
    declared_markets: Iterable[str],
    ci_attestation: Mapping[str, Any],
    clv_evidence: Mapping[str, Any],
    clv_attestation: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Build the only deployment-grade registry path for forward NFL evidence."""
    expected_code_sha = str(math_artifact.get("code_git_sha") or "").strip().lower()
    verified_clv = verify_nfl_forward_clv_attestation(
        clv_evidence, clv_attestation, expected_code_sha=expected_code_sha
    )
    registry = build_nfl_promotion_registry(
        math_artifact,
        historical_evidence,
        declared_markets=declared_markets,
        ci_attested=True,
        ci_attestation=ci_attestation,
        clv_evidence=clv_evidence,
    )
    registry["clv_attestation_state"] = "EXTERNALLY_ATTESTED"
    registry["clv_attestation"] = verified_clv
    return registry
