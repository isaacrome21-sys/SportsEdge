"""Hash-bound packaging for the selected CFB candidate production model.

Packaging only: no candidate evaluation, attempt consumption, Model_P, promotion,
eligibility, staking, evidence-clock, or OFFICIAL authority is created here.
"""
from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
from typing import Any, Mapping

from .candidate_model_v2 import candidate_feature_names
from .selected_candidate_model import (
    CFB_SELECTED_CANDIDATE_FEATURE_CONTRACT,
    CFB_SELECTED_CANDIDATE_MODEL_ID,
    CFBSelectedCandidateScoreModel,
)

CFB_SELECTED_CANDIDATE_ARTIFACT_SCHEMA = "CFB_SELECTED_CANDIDATE_MODEL_ARTIFACT_V1"
CFB_SELECTED_CANDIDATE_CODE_SURFACE = (
    "sportsedge/sports/cfb/candidate_registry_v2.py",
    "sportsedge/sports/cfb/candidate_variants.py",
    "sportsedge/sports/cfb/candidate_model_v2.py",
    "sportsedge/sports/cfb/selected_candidate_model.py",
    "sportsedge/sports/cfb/selected_candidate_artifact.py",
    "sportsedge/sports/cfb/run_machine.py",
    "sportsedge/sports/cfb/source.py",
    "sportsedge/sports/cfb/classification_policy.py",
)


class CFBSelectedCandidateArtifactError(ValueError):
    pass


def _hex64(value: Any, name: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise CFBSelectedCandidateArtifactError(f"{name}_INVALID")
    return text


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return sha256(raw).hexdigest()


def cfb_selected_candidate_code_surface_sha256(repo_root: str | Path) -> str:
    root = Path(repo_root).resolve()
    digest = sha256()
    for relative in CFB_SELECTED_CANDIDATE_CODE_SURFACE:
        path = root / relative
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise CFBSelectedCandidateArtifactError(f"CFB_SELECTED_CANDIDATE_CODE_SURFACE_UNREADABLE:{relative}") from exc
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(raw)
        digest.update(b"\0")
    return digest.hexdigest()


def build_cfb_selected_candidate_artifact(
    model: CFBSelectedCandidateScoreModel,
    *,
    model_code_sha256: str,
    training_source_sha256: str,
    selection_result_sha256: str,
) -> dict[str, Any]:
    if model.model_id != CFB_SELECTED_CANDIDATE_MODEL_ID or model.feature_contract != CFB_SELECTED_CANDIDATE_FEATURE_CONTRACT:
        raise CFBSelectedCandidateArtifactError("CFB_SELECTED_CANDIDATE_MODEL_IDENTITY_INVALID")
    expected_names = candidate_feature_names(model.family)
    if tuple(model.feature_names) != expected_names:
        raise CFBSelectedCandidateArtifactError("CFB_SELECTED_CANDIDATE_FEATURE_NAMES_MISMATCH")
    payload = {
        "schema_version": CFB_SELECTED_CANDIDATE_ARTIFACT_SCHEMA,
        "model_id": CFB_SELECTED_CANDIDATE_MODEL_ID,
        "feature_contract": CFB_SELECTED_CANDIDATE_FEATURE_CONTRACT,
        "candidate_family": model.family,
        "model_code_sha256": _hex64(model_code_sha256, "CFB_SELECTED_CANDIDATE_MODEL_CODE_SHA256"),
        "training_source_sha256": _hex64(training_source_sha256, "CFB_SELECTED_CANDIDATE_TRAINING_SOURCE_SHA256"),
        "selection_result_sha256": _hex64(selection_result_sha256, "CFB_SELECTED_CANDIDATE_SELECTION_RESULT_SHA256"),
        "model": asdict(model),
        "authority": {
            "model_p": False,
            "truth_gate": False,
            "promotion": False,
            "eligibility": False,
            "staking": False,
            "official": False,
            "historical_pit": False,
        },
    }
    payload["artifact_sha256"] = _canonical_hash(payload)
    return payload


def load_cfb_selected_candidate_artifact(
    payload: Mapping[str, Any],
    *,
    expected_model_code_sha256: str | None = None,
    expected_training_source_sha256: str | None = None,
    expected_selection_result_sha256: str | None = None,
) -> CFBSelectedCandidateScoreModel:
    if not isinstance(payload, Mapping):
        raise CFBSelectedCandidateArtifactError("CFB_SELECTED_CANDIDATE_ARTIFACT_MAPPING_REQUIRED")
    row = dict(payload)
    if row.get("schema_version") != CFB_SELECTED_CANDIDATE_ARTIFACT_SCHEMA:
        raise CFBSelectedCandidateArtifactError("CFB_SELECTED_CANDIDATE_ARTIFACT_SCHEMA_INVALID")
    if row.get("model_id") != CFB_SELECTED_CANDIDATE_MODEL_ID or row.get("feature_contract") != CFB_SELECTED_CANDIDATE_FEATURE_CONTRACT:
        raise CFBSelectedCandidateArtifactError("CFB_SELECTED_CANDIDATE_ARTIFACT_IDENTITY_INVALID")

    code_sha = _hex64(row.get("model_code_sha256"), "CFB_SELECTED_CANDIDATE_MODEL_CODE_SHA256")
    source_sha = _hex64(row.get("training_source_sha256"), "CFB_SELECTED_CANDIDATE_TRAINING_SOURCE_SHA256")
    selection_sha = _hex64(row.get("selection_result_sha256"), "CFB_SELECTED_CANDIDATE_SELECTION_RESULT_SHA256")
    if expected_model_code_sha256 is not None and code_sha != _hex64(expected_model_code_sha256, "CFB_EXPECTED_SELECTED_CANDIDATE_MODEL_CODE_SHA256"):
        raise CFBSelectedCandidateArtifactError("CFB_SELECTED_CANDIDATE_MODEL_CODE_SHA256_MISMATCH")
    if expected_training_source_sha256 is not None and source_sha != _hex64(expected_training_source_sha256, "CFB_EXPECTED_SELECTED_CANDIDATE_TRAINING_SOURCE_SHA256"):
        raise CFBSelectedCandidateArtifactError("CFB_SELECTED_CANDIDATE_TRAINING_SOURCE_SHA256_MISMATCH")
    if expected_selection_result_sha256 is not None and selection_sha != _hex64(expected_selection_result_sha256, "CFB_EXPECTED_SELECTED_CANDIDATE_SELECTION_RESULT_SHA256"):
        raise CFBSelectedCandidateArtifactError("CFB_SELECTED_CANDIDATE_SELECTION_RESULT_SHA256_MISMATCH")

    authority = row.get("authority")
    if not isinstance(authority, Mapping) or any(value is not False for value in authority.values()):
        raise CFBSelectedCandidateArtifactError("CFB_SELECTED_CANDIDATE_AUTHORITY_MUST_REMAIN_ZERO")

    claimed = _hex64(row.get("artifact_sha256"), "CFB_SELECTED_CANDIDATE_ARTIFACT_SHA256")
    unhashed = dict(row)
    unhashed.pop("artifact_sha256", None)
    if _canonical_hash(unhashed) != claimed:
        raise CFBSelectedCandidateArtifactError("CFB_SELECTED_CANDIDATE_ARTIFACT_HASH_MISMATCH")

    raw = row.get("model")
    if not isinstance(raw, Mapping):
        raise CFBSelectedCandidateArtifactError("CFB_SELECTED_CANDIDATE_MODEL_PAYLOAD_REQUIRED")
    family = str(row.get("candidate_family") or "")
    try:
        model = CFBSelectedCandidateScoreModel(
            model_id=str(raw.get("model_id")),
            feature_contract=str(raw.get("feature_contract")),
            family=str(raw.get("family")),
            feature_names=tuple(str(x) for x in raw.get("feature_names", ())),
            feature_means=tuple(float(x) for x in raw.get("feature_means", ())),
            feature_scales=tuple(float(x) for x in raw.get("feature_scales", ())),
            home_coefficients=tuple(float(x) for x in raw.get("home_coefficients", ())),
            away_coefficients=tuple(float(x) for x in raw.get("away_coefficients", ())),
            residual_pairs=tuple((float(a), float(b)) for a, b in raw.get("residual_pairs", ())),
            overtime_deltas=tuple((int(a), int(b)) for a, b in raw.get("overtime_deltas", ())),
            train_seasons=tuple(int(x) for x in raw.get("train_seasons", ())),
            ridge_alpha=float(raw.get("ridge_alpha")),
        )
    except (TypeError, ValueError) as exc:
        raise CFBSelectedCandidateArtifactError("CFB_SELECTED_CANDIDATE_ARTIFACT_FIELDS_INVALID") from exc

    if model.model_id != CFB_SELECTED_CANDIDATE_MODEL_ID or model.feature_contract != CFB_SELECTED_CANDIDATE_FEATURE_CONTRACT:
        raise CFBSelectedCandidateArtifactError("CFB_SELECTED_CANDIDATE_MODEL_PAYLOAD_IDENTITY_INVALID")
    if model.family != family:
        raise CFBSelectedCandidateArtifactError("CFB_SELECTED_CANDIDATE_FAMILY_BINDING_MISMATCH")
    expected_names = candidate_feature_names(family)
    if tuple(model.feature_names) != expected_names:
        raise CFBSelectedCandidateArtifactError("CFB_SELECTED_CANDIDATE_FEATURE_NAMES_MISMATCH")
    n = len(expected_names)
    if n == 0 or len(model.feature_means) != n or len(model.feature_scales) != n:
        raise CFBSelectedCandidateArtifactError("CFB_SELECTED_CANDIDATE_FEATURE_DIMENSIONS_INVALID")
    if len(model.home_coefficients) != n + 1 or len(model.away_coefficients) != n + 1:
        raise CFBSelectedCandidateArtifactError("CFB_SELECTED_CANDIDATE_COEFFICIENT_DIMENSIONS_INVALID")
    if not model.residual_pairs or not model.train_seasons:
        raise CFBSelectedCandidateArtifactError("CFB_SELECTED_CANDIDATE_TRAINING_SUPPORT_MISSING")
    numeric = [*model.feature_means, *model.feature_scales, *model.home_coefficients, *model.away_coefficients, model.ridge_alpha]
    numeric += [x for pair in model.residual_pairs for x in pair]
    if not all(isfinite(float(x)) for x in numeric) or any(float(x) <= 0 for x in model.feature_scales):
        raise CFBSelectedCandidateArtifactError("CFB_SELECTED_CANDIDATE_NUMERIC_STATE_INVALID")
    return model


__all__ = [
    "CFB_SELECTED_CANDIDATE_ARTIFACT_SCHEMA",
    "CFB_SELECTED_CANDIDATE_CODE_SURFACE",
    "CFBSelectedCandidateArtifactError",
    "build_cfb_selected_candidate_artifact",
    "cfb_selected_candidate_code_surface_sha256",
    "load_cfb_selected_candidate_artifact",
]
