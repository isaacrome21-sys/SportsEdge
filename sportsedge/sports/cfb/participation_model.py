"""Activation gate for the CFB player participation/substitution model.

The shared football prop simulator currently requires sport-specific participation
behavior before CFB can be bettor-facing. This module validates that prerequisite
without creating Model_P or granting promotion authority.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .participation_source_capture import (
    PARTICIPATION_CAPTURE_CONTRACT,
    PARTICIPATION_DATASETS,
)

DEFAULT_POLICY = Path("config/cfb_prop_participation_model_v1.json")
EXPECTED_SCHEMA = "CFB_PROP_PARTICIPATION_MODEL_V1"
EXPECTED_READINESS_CONTRACT = "CFB_PARTICIPATION_PIT_READINESS_V1"


class CFBParticipationModelError(ValueError):
    pass


def _hex(value: Any, length: int, code: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != length or any(ch not in "0123456789abcdef" for ch in text):
        raise CFBParticipationModelError(code)
    return text


def load_cfb_participation_policy(path: str | Path = DEFAULT_POLICY) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise CFBParticipationModelError("CFB_PROP_PARTICIPATION_POLICY_UNREADABLE") from exc
    if not isinstance(payload, Mapping):
        raise CFBParticipationModelError("CFB_PROP_PARTICIPATION_POLICY_INVALID")
    out = dict(payload)
    if out.get("schema_version") != EXPECTED_SCHEMA or str(out.get("sport") or "").upper() != "CFB":
        raise CFBParticipationModelError("CFB_PROP_PARTICIPATION_POLICY_IDENTITY_INVALID")
    if out.get("market_data_used_as_feature") is not False:
        raise CFBParticipationModelError("CFB_PROP_PARTICIPATION_MARKET_FEATURE_FORBIDDEN")
    if out.get("promotion_authority") is not False or out.get("activation_authority") is not False:
        raise CFBParticipationModelError("CFB_PROP_PARTICIPATION_AUTHORITY_INVALID")
    blockers = out.get("structural_blockers")
    if not isinstance(blockers, list) or not blockers:
        raise CFBParticipationModelError("CFB_PROP_PARTICIPATION_BLOCKERS_REQUIRED")

    sources = out.get("training_source_requirements")
    if not isinstance(sources, Mapping):
        raise CFBParticipationModelError("CFB_PROP_PARTICIPATION_SOURCE_REQUIREMENTS_MISSING")
    if sources.get("point_in_time_mode") != "FORWARD_CAPTURE_ONLY":
        raise CFBParticipationModelError("CFB_PROP_PARTICIPATION_PIT_MODE_INVALID")
    if sources.get("retroactive_backfill_allowed") is not False:
        raise CFBParticipationModelError("CFB_PROP_PARTICIPATION_RETROACTIVE_BACKFILL_FORBIDDEN")
    if sources.get("market_data_allowed") is not False:
        raise CFBParticipationModelError("CFB_PROP_PARTICIPATION_MARKET_SOURCE_FORBIDDEN")
    declared_datasets = sources.get("required_datasets")
    if not isinstance(declared_datasets, list) or set(map(str, declared_datasets)) != set(PARTICIPATION_DATASETS):
        raise CFBParticipationModelError("CFB_PROP_PARTICIPATION_SOURCE_DATASETS_INVALID")
    if sources.get("capture_contract") != PARTICIPATION_CAPTURE_CONTRACT:
        raise CFBParticipationModelError("CFB_PROP_PARTICIPATION_CAPTURE_CONTRACT_INVALID")
    if sources.get("readiness_contract") != EXPECTED_READINESS_CONTRACT:
        raise CFBParticipationModelError("CFB_PROP_PARTICIPATION_READINESS_CONTRACT_INVALID")
    if sources.get("persist_branch") != "data":
        raise CFBParticipationModelError("CFB_PROP_PARTICIPATION_PERSIST_BRANCH_INVALID")
    if sources.get("persist_path_prefix") != "history/cfb/forward-participation":
        raise CFBParticipationModelError("CFB_PROP_PARTICIPATION_PERSIST_PATH_INVALID")
    return out


def require_frozen_cfb_participation_model(
    path: str | Path = DEFAULT_POLICY,
) -> dict[str, Any]:
    payload = load_cfb_participation_policy(path)
    if payload.get("status") != "FROZEN":
        raise CFBParticipationModelError("CFB_PROP_PARTICIPATION_MODEL_NOT_FROZEN")
    if payload.get("engine_validation_status") != "PASSED":
        raise CFBParticipationModelError("CFB_PROP_PARTICIPATION_MODEL_NOT_FORWARD_VALIDATED")
    artifact_path = str(payload.get("artifact_path") or "").strip()
    if not artifact_path:
        raise CFBParticipationModelError("CFB_PROP_PARTICIPATION_ARTIFACT_PATH_REQUIRED")
    payload["artifact_sha256"] = _hex(
        payload.get("artifact_sha256"), 64, "CFB_PROP_PARTICIPATION_ARTIFACT_SHA256_INVALID"
    )
    payload["fit_code_git_sha"] = _hex(
        payload.get("fit_code_git_sha"), 40, "CFB_PROP_PARTICIPATION_FIT_CODE_SHA_INVALID"
    )
    payload["training_source_manifest_sha256"] = _hex(
        payload.get("training_source_manifest_sha256"),
        64,
        "CFB_PROP_PARTICIPATION_TRAINING_SOURCE_SHA256_INVALID",
    )
    evidence = payload.get("required_evidence")
    if not isinstance(evidence, list) or {
        "point_in_time_training_source_manifest",
        "deterministic_same_source_same_sha_replay",
        "independent_forward_holdout",
        "artifact_bound_validation_report",
    } - {str(item) for item in evidence}:
        raise CFBParticipationModelError("CFB_PROP_PARTICIPATION_EVIDENCE_CONTRACT_INVALID")
    return payload


__all__ = [
    "CFBParticipationModelError",
    "DEFAULT_POLICY",
    "load_cfb_participation_policy",
    "require_frozen_cfb_participation_model",
]
