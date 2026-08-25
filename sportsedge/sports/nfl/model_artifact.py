"""Hash-manifest-bound serialization for the exact production NFL M2 model."""
from __future__ import annotations

from dataclasses import asdict
from math import isfinite
import re
from typing import Any, Mapping

from .m2 import NFLM2ScoreModel, NFL_M2_FEATURE_CONTRACT, PRODUCTION_NFL_M2_MODEL_ID

_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _git_sha(value: Any, error: str) -> str:
    raw = str(value or "").strip().lower()
    if not _GIT_SHA_RE.fullmatch(raw):
        raise ValueError(error)
    return raw


def _hash(value: Any, error: str) -> str:
    raw = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(raw):
        raise ValueError(error)
    return raw


def _finite_sequence(value: Any, field: str) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"NFL_M2_MODEL_ARTIFACT_FIELD_INVALID:{field}")
    out = tuple(float(x) for x in value)
    if not all(isfinite(x) for x in out):
        raise ValueError("NFL_M2_MODEL_ARTIFACT_NONFINITE")
    return out


def build_nfl_m2_model_artifact(
    model: NFLM2ScoreModel,
    *,
    code_git_sha: str,
    source_manifest_sha256: str,
) -> dict[str, Any]:
    if model.model_id != PRODUCTION_NFL_M2_MODEL_ID:
        raise ValueError("NFL_M2_MODEL_ARTIFACT_MODEL_ID_MISMATCH")
    if model.feature_contract != NFL_M2_FEATURE_CONTRACT:
        raise ValueError("NFL_M2_MODEL_ARTIFACT_FEATURE_CONTRACT_MISMATCH")
    code_sha = _git_sha(code_git_sha, "NFL_M2_MODEL_ARTIFACT_CODE_SHA_INVALID")
    source_sha = _hash(source_manifest_sha256, "NFL_M2_MODEL_ARTIFACT_SOURCE_SHA256_INVALID")
    if not model.train_seasons:
        raise ValueError("NFL_M2_MODEL_ARTIFACT_TRAIN_SEASONS_EMPTY")
    payload = asdict(model)
    return {
        "schema_version": 1,
        "sport": "nfl",
        "model_id": PRODUCTION_NFL_M2_MODEL_ID,
        "feature_contract": NFL_M2_FEATURE_CONTRACT,
        "code_git_sha": code_sha,
        "source_manifest_sha256": source_sha,
        "trained_through_season": max(int(x) for x in model.train_seasons),
        "model": payload,
    }


def load_nfl_m2_model_artifact(
    payload: Mapping[str, Any],
    *,
    expected_code_git_sha: str | None = None,
    expected_source_manifest_sha256: str | None = None,
) -> NFLM2ScoreModel:
    if not isinstance(payload, Mapping):
        raise ValueError("NFL_M2_MODEL_ARTIFACT_NOT_OBJECT")
    if int(payload.get("schema_version", 0)) != 1:
        raise ValueError("NFL_M2_MODEL_ARTIFACT_SCHEMA_INVALID")
    if str(payload.get("sport") or "").lower() != "nfl":
        raise ValueError("NFL_M2_MODEL_ARTIFACT_SPORT_MISMATCH")
    if payload.get("model_id") != PRODUCTION_NFL_M2_MODEL_ID:
        raise ValueError("NFL_M2_MODEL_ARTIFACT_MODEL_ID_MISMATCH")
    if payload.get("feature_contract") != NFL_M2_FEATURE_CONTRACT:
        raise ValueError("NFL_M2_MODEL_ARTIFACT_FEATURE_CONTRACT_MISMATCH")
    code_sha = _git_sha(payload.get("code_git_sha"), "NFL_M2_MODEL_ARTIFACT_CODE_SHA_INVALID")
    source_sha = _hash(payload.get("source_manifest_sha256"), "NFL_M2_MODEL_ARTIFACT_SOURCE_SHA256_INVALID")
    if expected_code_git_sha is not None and code_sha != _git_sha(
        expected_code_git_sha, "NFL_M2_MODEL_ARTIFACT_EXPECTED_CODE_SHA_INVALID"
    ):
        raise ValueError("NFL_M2_MODEL_ARTIFACT_CODE_SHA_MISMATCH")
    if expected_source_manifest_sha256 is not None and source_sha != _hash(
        expected_source_manifest_sha256, "NFL_M2_MODEL_ARTIFACT_EXPECTED_SOURCE_SHA256_INVALID"
    ):
        raise ValueError("NFL_M2_MODEL_ARTIFACT_SOURCE_MISMATCH")

    raw = payload.get("model")
    if not isinstance(raw, Mapping):
        raise ValueError("NFL_M2_MODEL_ARTIFACT_MODEL_REQUIRED")
    if raw.get("model_id") != PRODUCTION_NFL_M2_MODEL_ID:
        raise ValueError("NFL_M2_MODEL_ARTIFACT_MODEL_ID_MISMATCH")
    if raw.get("feature_contract") != NFL_M2_FEATURE_CONTRACT:
        raise ValueError("NFL_M2_MODEL_ARTIFACT_FEATURE_CONTRACT_MISMATCH")

    feature_names_raw = raw.get("feature_names")
    if not isinstance(feature_names_raw, (list, tuple)) or not feature_names_raw:
        raise ValueError("NFL_M2_MODEL_ARTIFACT_FEATURE_NAMES_INVALID")
    feature_names = tuple(str(x) for x in feature_names_raw)
    if any(not x for x in feature_names):
        raise ValueError("NFL_M2_MODEL_ARTIFACT_FEATURE_NAMES_INVALID")
    means = _finite_sequence(raw.get("feature_means"), "feature_means")
    scales = _finite_sequence(raw.get("feature_scales"), "feature_scales")
    margin_coef = _finite_sequence(raw.get("margin_coefficients"), "margin_coefficients")
    total_coef = _finite_sequence(raw.get("total_coefficients"), "total_coefficients")
    if len(means) != len(feature_names) or len(scales) != len(feature_names):
        raise ValueError("NFL_M2_MODEL_ARTIFACT_FEATURE_DIMENSION_MISMATCH")
    if len(margin_coef) != len(feature_names) + 1 or len(total_coef) != len(feature_names) + 1:
        raise ValueError("NFL_M2_MODEL_ARTIFACT_COEFFICIENT_DIMENSION_MISMATCH")
    if any(x <= 0.0 for x in scales):
        raise ValueError("NFL_M2_MODEL_ARTIFACT_SCALE_INVALID")

    seasons_raw = raw.get("train_seasons")
    if not isinstance(seasons_raw, (list, tuple)) or not seasons_raw:
        raise ValueError("NFL_M2_MODEL_ARTIFACT_TRAIN_SEASONS_EMPTY")
    seasons = tuple(int(x) for x in seasons_raw)
    ridge_alpha = float(raw.get("ridge_alpha"))
    margin_sigma = float(raw.get("margin_sigma"))
    total_sigma = float(raw.get("total_sigma"))
    corr = float(raw.get("residual_correlation"))
    if not all(isfinite(x) for x in (ridge_alpha, margin_sigma, total_sigma, corr)):
        raise ValueError("NFL_M2_MODEL_ARTIFACT_NONFINITE")
    if ridge_alpha < 0 or margin_sigma <= 0 or total_sigma <= 0 or not -1.0 <= corr <= 1.0:
        raise ValueError("NFL_M2_MODEL_ARTIFACT_NUMERIC_RANGE_INVALID")

    pairs_raw = raw.get("residual_pairs")
    if not isinstance(pairs_raw, (list, tuple)) or not pairs_raw:
        raise ValueError("NFL_M2_MODEL_ARTIFACT_RESIDUALS_EMPTY")
    pairs: list[tuple[float, float]] = []
    for pair in pairs_raw:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError("NFL_M2_MODEL_ARTIFACT_RESIDUAL_PAIR_INVALID")
        left, right = float(pair[0]), float(pair[1])
        if not isfinite(left) or not isfinite(right):
            raise ValueError("NFL_M2_MODEL_ARTIFACT_NONFINITE")
        pairs.append((left, right))

    through = int(payload.get("trained_through_season", 0))
    if through != max(seasons):
        raise ValueError("NFL_M2_MODEL_ARTIFACT_TRAINED_THROUGH_MISMATCH")

    return NFLM2ScoreModel(
        model_id=PRODUCTION_NFL_M2_MODEL_ID,
        feature_contract=NFL_M2_FEATURE_CONTRACT,
        feature_names=feature_names,
        feature_means=means,
        feature_scales=scales,
        margin_coefficients=margin_coef,
        total_coefficients=total_coef,
        train_seasons=seasons,
        ridge_alpha=ridge_alpha,
        margin_sigma=margin_sigma,
        total_sigma=total_sigma,
        residual_correlation=corr,
        residual_pairs=tuple(pairs),
    )
