"""Hash-bound serialization for the canonical CFB joint score model.

This module is packaging only. It does not fit, calibrate, promote, or otherwise
change the CFB model. Runtime loading fails closed on schema, model identity,
code-surface identity, source identity, dimensions, or artifact hash mismatch.
"""
from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
from typing import Any, Mapping

from .joint_model import CFB_FEATURE_CONTRACT, CFB_JOINT_MODEL_ID, CFBJointScoreModel

CFB_MODEL_ARTIFACT_SCHEMA = "CFB_JOINT_MODEL_ARTIFACT_V1"
CFB_MODEL_CODE_SURFACE = (
    "sportsedge/sports/cfb/joint_model.py",
    "sportsedge/sports/cfb/run_machine.py",
    "sportsedge/sports/cfb/source.py",
    "sportsedge/sports/cfb/classification_policy.py",
)


class CFBModelArtifactError(ValueError):
    pass


def _hex64(value: Any, name: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise CFBModelArtifactError(f"{name}_INVALID")
    return text


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return sha256(raw).hexdigest()


def cfb_model_code_surface_sha256(repo_root: str | Path) -> str:
    root = Path(repo_root).resolve()
    digest = sha256()
    for relative in CFB_MODEL_CODE_SURFACE:
        path = root / relative
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise CFBModelArtifactError(f"CFB_MODEL_CODE_SURFACE_UNREADABLE:{relative}") from exc
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(raw)
        digest.update(b"\0")
    return digest.hexdigest()


def build_cfb_model_artifact(
    model: CFBJointScoreModel,
    *,
    model_code_sha256: str,
    training_source_sha256: str,
) -> dict[str, Any]:
    if model.model_id != CFB_JOINT_MODEL_ID or model.feature_contract != CFB_FEATURE_CONTRACT:
        raise CFBModelArtifactError("CFB_MODEL_IDENTITY_INVALID")
    payload = {
        "schema_version": CFB_MODEL_ARTIFACT_SCHEMA,
        "model_id": CFB_JOINT_MODEL_ID,
        "feature_contract": CFB_FEATURE_CONTRACT,
        "model_code_sha256": _hex64(model_code_sha256, "CFB_MODEL_CODE_SHA256"),
        "training_source_sha256": _hex64(training_source_sha256, "CFB_TRAINING_SOURCE_SHA256"),
        "model": asdict(model),
    }
    payload["artifact_sha256"] = _canonical_hash(payload)
    return payload


def load_cfb_model_artifact(
    payload: Mapping[str, Any],
    *,
    expected_model_code_sha256: str | None = None,
    expected_training_source_sha256: str | None = None,
) -> CFBJointScoreModel:
    if not isinstance(payload, Mapping):
        raise CFBModelArtifactError("CFB_MODEL_ARTIFACT_MAPPING_REQUIRED")
    row = dict(payload)
    if row.get("schema_version") != CFB_MODEL_ARTIFACT_SCHEMA:
        raise CFBModelArtifactError("CFB_MODEL_ARTIFACT_SCHEMA_INVALID")
    if row.get("model_id") != CFB_JOINT_MODEL_ID or row.get("feature_contract") != CFB_FEATURE_CONTRACT:
        raise CFBModelArtifactError("CFB_MODEL_ARTIFACT_IDENTITY_INVALID")
    code_sha = _hex64(row.get("model_code_sha256"), "CFB_MODEL_CODE_SHA256")
    source_sha = _hex64(row.get("training_source_sha256"), "CFB_TRAINING_SOURCE_SHA256")
    if expected_model_code_sha256 is not None and code_sha != _hex64(expected_model_code_sha256, "CFB_EXPECTED_MODEL_CODE_SHA256"):
        raise CFBModelArtifactError("CFB_MODEL_CODE_SHA256_MISMATCH")
    if expected_training_source_sha256 is not None and source_sha != _hex64(expected_training_source_sha256, "CFB_EXPECTED_TRAINING_SOURCE_SHA256"):
        raise CFBModelArtifactError("CFB_TRAINING_SOURCE_SHA256_MISMATCH")
    claimed = _hex64(row.get("artifact_sha256"), "CFB_MODEL_ARTIFACT_SHA256")
    unhashed = dict(row)
    unhashed.pop("artifact_sha256", None)
    if _canonical_hash(unhashed) != claimed:
        raise CFBModelArtifactError("CFB_MODEL_ARTIFACT_HASH_MISMATCH")

    raw = row.get("model")
    if not isinstance(raw, Mapping):
        raise CFBModelArtifactError("CFB_MODEL_PAYLOAD_REQUIRED")
    try:
        model = CFBJointScoreModel(
            model_id=str(raw.get("model_id")),
            feature_contract=str(raw.get("feature_contract")),
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
        raise CFBModelArtifactError("CFB_MODEL_ARTIFACT_FIELDS_INVALID") from exc
    if model.model_id != CFB_JOINT_MODEL_ID or model.feature_contract != CFB_FEATURE_CONTRACT:
        raise CFBModelArtifactError("CFB_MODEL_PAYLOAD_IDENTITY_INVALID")
    n = len(model.feature_names)
    if n == 0 or len(model.feature_means) != n or len(model.feature_scales) != n:
        raise CFBModelArtifactError("CFB_MODEL_FEATURE_DIMENSIONS_INVALID")
    if len(model.home_coefficients) != n + 1 or len(model.away_coefficients) != n + 1:
        raise CFBModelArtifactError("CFB_MODEL_COEFFICIENT_DIMENSIONS_INVALID")
    if not model.residual_pairs or not model.train_seasons:
        raise CFBModelArtifactError("CFB_MODEL_TRAINING_SUPPORT_MISSING")
    numeric = [*model.feature_means, *model.feature_scales, *model.home_coefficients, *model.away_coefficients, model.ridge_alpha]
    numeric += [x for pair in model.residual_pairs for x in pair]
    if not all(isfinite(float(x)) for x in numeric) or any(float(x) <= 0 for x in model.feature_scales):
        raise CFBModelArtifactError("CFB_MODEL_NUMERIC_STATE_INVALID")
    return model
