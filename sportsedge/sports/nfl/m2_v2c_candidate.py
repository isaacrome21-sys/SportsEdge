"""NFL M2 V2C diagnostic: independently regularized margin and total means.

This candidate isolates a specific production limitation: V1 uses one ridge penalty
for both the margin and total regressions. V2C keeps the exact market-blind feature
contract and paired training residual replay, but allows independent ridge penalties
for the two conditional means. The penalties must be chosen from training-only
inner walk-forward evidence by the companion selector.

No sportsbook line, price, closing result, or held-out outcome is consumed while
fitting or deriving a held-out distribution.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt
from typing import Any, Iterable

import numpy as np

from .m2 import (
    NFL_M2_FEATURE_CONTRACT,
    _game_feature_vector,
    _reconcile_scores,
    _ridge_coefficients,
    _target_scores,
)

NFL_M2_V2C_CANDIDATE_MODEL_ID = "nfl_m2_split_ridge_v2c_candidate"
NFL_M2_V2C_DISTRIBUTION_CONTRACT = "NFL_M2_V2C_SPLIT_RIDGE_PAIRED_RESIDUAL_V1"


@dataclass(frozen=True)
class NFLM2V2CCandidateModel:
    model_id: str
    feature_contract: str
    distribution_contract: str
    feature_means: tuple[float, ...]
    feature_scales: tuple[float, ...]
    margin_coefficients: tuple[float, ...]
    total_coefficients: tuple[float, ...]
    train_seasons: tuple[int, ...]
    margin_ridge_alpha: float
    total_ridge_alpha: float
    residual_pairs: tuple[tuple[float, float], ...]
    margin_sigma: float
    total_sigma: float

    def predict(self, row: dict[str, Any]) -> tuple[float, float]:
        raw = np.asarray(_game_feature_vector(row), dtype=float)
        means = np.asarray(self.feature_means, dtype=float)
        scales = np.asarray(self.feature_scales, dtype=float)
        if raw.shape != means.shape or raw.shape != scales.shape:
            raise ValueError("NFL_M2_V2C_FEATURE_DIMENSION_MISMATCH")
        design = np.concatenate(([1.0], (raw - means) / scales))
        margin = float(design @ np.asarray(self.margin_coefficients, dtype=float))
        total = float(design @ np.asarray(self.total_coefficients, dtype=float))
        if not isfinite(margin) or not isfinite(total):
            raise ValueError("NFL_M2_V2C_PREDICTION_NONFINITE")
        return margin, total


def _alpha(value: Any, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"NFL_M2_V2C_{field}_INVALID") from exc
    if not isfinite(out) or out < 0.0:
        raise ValueError(f"NFL_M2_V2C_{field}_INVALID")
    return out


def fit_nfl_m2_v2c_candidate(
    rows: Iterable[dict[str, Any]],
    *,
    margin_ridge_alpha: float = 10.0,
    total_ridge_alpha: float = 10.0,
) -> NFLM2V2CCandidateModel:
    data = [dict(row) for row in rows]
    if len(data) < 2:
        raise ValueError("NFL_M2_V2C_TRAINING_ROWS_INSUFFICIENT")
    margin_alpha = _alpha(margin_ridge_alpha, "MARGIN_ALPHA")
    total_alpha = _alpha(total_ridge_alpha, "TOTAL_ALPHA")

    raw_x = np.asarray([_game_feature_vector(row) for row in data], dtype=float)
    if raw_x.ndim != 2 or raw_x.shape[0] != len(data):
        raise ValueError("NFL_M2_V2C_TRAINING_MATRIX_INVALID")
    means = raw_x.mean(axis=0)
    scales = raw_x.std(axis=0)
    scales = np.where(scales > 1e-12, scales, 1.0)
    design = np.column_stack((np.ones(len(data), dtype=float), (raw_x - means) / scales))

    targets = [_target_scores(row) for row in data]
    margin_y = np.asarray([target[0] for target in targets], dtype=float)
    total_y = np.asarray([target[1] for target in targets], dtype=float)
    margin_coef = _ridge_coefficients(design, margin_y, margin_alpha)
    total_coef = _ridge_coefficients(design, total_y, total_alpha)

    margin_residual = margin_y - design @ margin_coef
    total_residual = total_y - design @ total_coef
    margin_sigma = float(sqrt(float(np.mean(margin_residual ** 2))))
    total_sigma = float(sqrt(float(np.mean(total_residual ** 2))))
    if margin_sigma <= 1e-12 or total_sigma <= 1e-12:
        raise ValueError("NFL_M2_V2C_RESIDUAL_SIGMA_ZERO")

    train_seasons = tuple(sorted({int(row["season"]) for row in data}))
    if not train_seasons:
        raise ValueError("NFL_M2_V2C_TRAINING_SEASONS_REQUIRED")
    residual_pairs = tuple(
        (float(margin), float(total))
        for margin, total in zip(margin_residual.tolist(), total_residual.tolist())
    )
    return NFLM2V2CCandidateModel(
        model_id=NFL_M2_V2C_CANDIDATE_MODEL_ID,
        feature_contract=NFL_M2_FEATURE_CONTRACT,
        distribution_contract=NFL_M2_V2C_DISTRIBUTION_CONTRACT,
        feature_means=tuple(float(value) for value in means.tolist()),
        feature_scales=tuple(float(value) for value in scales.tolist()),
        margin_coefficients=tuple(float(value) for value in margin_coef.tolist()),
        total_coefficients=tuple(float(value) for value in total_coef.tolist()),
        train_seasons=train_seasons,
        margin_ridge_alpha=margin_alpha,
        total_ridge_alpha=total_alpha,
        residual_pairs=residual_pairs,
        margin_sigma=margin_sigma,
        total_sigma=total_sigma,
    )


def derive_nfl_m2_v2c_score_distribution(
    model: NFLM2V2CCandidateModel,
    row: dict[str, Any],
) -> tuple[dict[str, int], ...]:
    if model.model_id != NFL_M2_V2C_CANDIDATE_MODEL_ID:
        raise ValueError("NFL_M2_V2C_MODEL_IDENTITY_INVALID")
    if model.feature_contract != NFL_M2_FEATURE_CONTRACT:
        raise ValueError("NFL_M2_V2C_FEATURE_CONTRACT_INVALID")
    if model.distribution_contract != NFL_M2_V2C_DISTRIBUTION_CONTRACT:
        raise ValueError("NFL_M2_V2C_DISTRIBUTION_CONTRACT_INVALID")
    if not model.residual_pairs:
        raise ValueError("NFL_M2_V2C_RESIDUAL_DISTRIBUTION_MISSING")
    margin_mu, total_mu = model.predict(dict(row))
    return tuple(
        _reconcile_scores(margin_mu + margin_residual, total_mu + total_residual)
        for margin_residual, total_residual in model.residual_pairs
    )
