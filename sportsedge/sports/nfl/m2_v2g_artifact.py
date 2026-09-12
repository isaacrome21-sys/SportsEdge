"""Deterministic, research-only artifact contract for the NFL V2G candidate.

This module serializes an already-fitted V2G candidate together with immutable
training/source provenance. It does not fetch history, fit from unbound bytes,
promote a market, create production Model_P, or authorize a bet.
"""
from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
from typing import Any, Mapping

from .m2_v2g_candidate import (
    NFLM2V2GCandidateModel,
    NFL_M2_V2G_CANDIDATE_MODEL_ID,
    NFL_M2_V2G_DISTRIBUTION_CONTRACT,
    NFL_M2_V2G_EVENT_CONTRACT,
)

ARTIFACT_SCHEMA = "NFL_M2_V2G_RESEARCH_ARTIFACT_V1"
FREEZE_SCHEMA = "SPORTSEDGE_NFL_V2G_IMPLEMENTATION_FREEZE_V1"


class NFLV2GArtifactError(ValueError):
    pass


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise NFLV2GArtifactError(code)


def _hex(value: Any, length: int, field: str) -> str:
    text = str(value or "").strip().lower()
    _require(len(text) == length and all(ch in "0123456789abcdef" for ch in text), f"NFL_V2G_ARTIFACT_HASH_INVALID:{field}")
    return text


def canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")


def artifact_sha256(payload: Mapping[str, Any]) -> str:
    return sha256(canonical_bytes(payload)).hexdigest()


def _model_payload(model: NFLM2V2GCandidateModel) -> dict[str, Any]:
    _require(model.model_id == NFL_M2_V2G_CANDIDATE_MODEL_ID, "NFL_V2G_ARTIFACT_MODEL_ID_MISMATCH")
    _require(model.distribution_contract == NFL_M2_V2G_DISTRIBUTION_CONTRACT, "NFL_V2G_ARTIFACT_DISTRIBUTION_CONTRACT_MISMATCH")
    _require(model.event_contract == NFL_M2_V2G_EVENT_CONTRACT, "NFL_V2G_ARTIFACT_EVENT_CONTRACT_MISMATCH")
    return {
        "model_id": model.model_id,
        "distribution_contract": model.distribution_contract,
        "event_contract": model.event_contract,
        "train_seasons": list(model.train_seasons),
        "league_drives_per_team_game": model.league_drives_per_team_game,
        "league_td_rate": model.league_td_rate,
        "league_fg_rate": model.league_fg_rate,
        "team_state": {team: asdict(model.team_state[team]) for team in sorted(model.team_state)},
        "prior_drives": model.prior_drives,
        "max_touchdowns": model.max_touchdowns,
        "max_field_goals": model.max_field_goals,
    }


def validate_implementation_freeze(freeze: Mapping[str, Any]) -> dict[str, str]:
    _require(freeze.get("schema_version") == FREEZE_SCHEMA, "NFL_V2G_ARTIFACT_FREEZE_SCHEMA_INVALID")
    _require(freeze.get("status") == "FROZEN_IMPLEMENTATION_IDENTITY", "NFL_V2G_ARTIFACT_IMPLEMENTATION_NOT_FROZEN")
    _require(freeze.get("candidate_id") == NFL_M2_V2G_CANDIDATE_MODEL_ID, "NFL_V2G_ARTIFACT_FREEZE_MODEL_ID_MISMATCH")
    _require(freeze.get("distribution_contract") == NFL_M2_V2G_DISTRIBUTION_CONTRACT, "NFL_V2G_ARTIFACT_FREEZE_DISTRIBUTION_MISMATCH")
    _require(freeze.get("event_contract") == NFL_M2_V2G_EVENT_CONTRACT, "NFL_V2G_ARTIFACT_FREEZE_EVENT_MISMATCH")
    _require(freeze.get("promotion_authority") is False, "NFL_V2G_ARTIFACT_FREEZE_PROMOTION_FORBIDDEN")
    _require(freeze.get("may_create_model_p") is False, "NFL_V2G_ARTIFACT_FREEZE_MODEL_P_FORBIDDEN")
    return {
        "implementation_commit_sha": _hex(freeze.get("implementation_commit_sha"), 40, "implementation_commit_sha"),
        "candidate_source_git_blob_sha1": _hex(freeze.get("candidate_source_git_blob_sha1"), 40, "candidate_source_git_blob_sha1"),
        "preregistration_commit_sha": _hex(freeze.get("preregistration_commit_sha"), 40, "preregistration_commit_sha"),
    }


def build_v2g_research_artifact(
    model: NFLM2V2GCandidateModel,
    *,
    implementation_freeze: Mapping[str, Any],
    training_event_rows_sha256: str,
    source_manifest_sha256: str,
) -> dict[str, Any]:
    """Build a deterministic non-promotional artifact from a fitted V2G model."""
    frozen = validate_implementation_freeze(implementation_freeze)
    training_sha = _hex(training_event_rows_sha256, 64, "training_event_rows_sha256")
    manifest_sha = _hex(source_manifest_sha256, 64, "source_manifest_sha256")
    return {
        "schema_version": ARTIFACT_SCHEMA,
        "status": "RESEARCH_ARTIFACT_ONLY",
        "candidate_id": NFL_M2_V2G_CANDIDATE_MODEL_ID,
        "distribution_contract": NFL_M2_V2G_DISTRIBUTION_CONTRACT,
        "event_contract": NFL_M2_V2G_EVENT_CONTRACT,
        **frozen,
        "training_event_rows_sha256": training_sha,
        "source_manifest_sha256": manifest_sha,
        "model": _model_payload(model),
        "promotion_authority": False,
        "production_model_changed": False,
        "market_eligibility_changed": False,
        "may_create_model_p": False,
        "official_status_granted": False,
    }


def validate_v2g_research_artifact(payload: Mapping[str, Any], *, implementation_freeze: Mapping[str, Any]) -> str:
    """Validate identity/provenance and return the canonical artifact SHA-256."""
    frozen = validate_implementation_freeze(implementation_freeze)
    _require(payload.get("schema_version") == ARTIFACT_SCHEMA, "NFL_V2G_ARTIFACT_SCHEMA_INVALID")
    _require(payload.get("status") == "RESEARCH_ARTIFACT_ONLY", "NFL_V2G_ARTIFACT_STATUS_INVALID")
    _require(payload.get("candidate_id") == NFL_M2_V2G_CANDIDATE_MODEL_ID, "NFL_V2G_ARTIFACT_MODEL_ID_MISMATCH")
    _require(payload.get("distribution_contract") == NFL_M2_V2G_DISTRIBUTION_CONTRACT, "NFL_V2G_ARTIFACT_DISTRIBUTION_CONTRACT_MISMATCH")
    _require(payload.get("event_contract") == NFL_M2_V2G_EVENT_CONTRACT, "NFL_V2G_ARTIFACT_EVENT_CONTRACT_MISMATCH")
    for field, expected in frozen.items():
        _require(str(payload.get(field) or "").lower() == expected, f"NFL_V2G_ARTIFACT_FREEZE_BINDING_MISMATCH:{field}")
    _hex(payload.get("training_event_rows_sha256"), 64, "training_event_rows_sha256")
    _hex(payload.get("source_manifest_sha256"), 64, "source_manifest_sha256")
    model = payload.get("model")
    _require(isinstance(model, Mapping), "NFL_V2G_ARTIFACT_MODEL_PAYLOAD_REQUIRED")
    _require(model.get("model_id") == NFL_M2_V2G_CANDIDATE_MODEL_ID, "NFL_V2G_ARTIFACT_MODEL_PAYLOAD_ID_MISMATCH")
    _require(model.get("distribution_contract") == NFL_M2_V2G_DISTRIBUTION_CONTRACT, "NFL_V2G_ARTIFACT_MODEL_PAYLOAD_DISTRIBUTION_MISMATCH")
    _require(model.get("event_contract") == NFL_M2_V2G_EVENT_CONTRACT, "NFL_V2G_ARTIFACT_MODEL_PAYLOAD_EVENT_MISMATCH")
    _require(payload.get("promotion_authority") is False, "NFL_V2G_ARTIFACT_PROMOTION_FORBIDDEN")
    _require(payload.get("production_model_changed") is False, "NFL_V2G_ARTIFACT_PRODUCTION_CHANGE_FORBIDDEN")
    _require(payload.get("market_eligibility_changed") is False, "NFL_V2G_ARTIFACT_ELIGIBILITY_CHANGE_FORBIDDEN")
    _require(payload.get("may_create_model_p") is False, "NFL_V2G_ARTIFACT_MODEL_P_FORBIDDEN")
    _require(payload.get("official_status_granted") is False, "NFL_V2G_ARTIFACT_OFFICIAL_FORBIDDEN")
    return artifact_sha256(payload)
