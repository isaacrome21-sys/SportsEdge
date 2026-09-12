"""NFL M2 V2D diagnostic: structured market-blind mean + discrete score support.

V2D changes the mean representation rather than the frozen gates. Margin is fit on
home-minus-away feature differentials. Total is fit on swap-invariant shared state
plus absolute matchup differentials. A training-only empirical integer score
support layer then supplies the NFL scoring lattice. No sportsbook line, price,
key-number target, or held-out outcome enters fit or distribution construction.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite, sqrt
from typing import Any, Iterable

import numpy as np

from .m2 import (
    NFL_M2_FEATURE_CONTRACT,
    _MODEL_FEATURES,
    _ridge_coefficients,
    _target_scores,
    _validated_feature_vector,
)
from .m2_v2_candidate import _integer_score

NFL_M2_V2D_CANDIDATE_MODEL_ID = "nfl_m2_structured_mean_discrete_support_v2d_candidate"
NFL_M2_V2D_DISTRIBUTION_CONTRACT = "NFL_M2_V2D_STRUCTURED_MEAN_EMPIRICAL_SCORE_SUPPORT_V1"


@dataclass(frozen=True)
class NFLM2V2DMeanModel:
    feature_contract: str
    feature_names: tuple[str, ...]
    diff_means: tuple[float, ...]
    diff_scales: tuple[float, ...]
    total_means: tuple[float, ...]
    total_scales: tuple[float, ...]
    margin_coefficients: tuple[float, ...]
    total_coefficients: tuple[float, ...]
    train_seasons: tuple[int, ...]
    ridge_alpha: float
    margin_sigma: float
    total_sigma: float

    @property
    def margin_home_field_intercept(self) -> float:
        return float(self.margin_coefficients[0])

    def predict(self, row: dict[str, Any]) -> tuple[float, float]:
        diff, total_basis = _structured_basis(row)
        dmeans = np.asarray(self.diff_means, dtype=float)
        dscales = np.asarray(self.diff_scales, dtype=float)
        tmeans = np.asarray(self.total_means, dtype=float)
        tscales = np.asarray(self.total_scales, dtype=float)
        if diff.shape != dmeans.shape or diff.shape != dscales.shape:
            raise ValueError("NFL_M2_V2D_MARGIN_FEATURE_DIMENSION_MISMATCH")
        if total_basis.shape != tmeans.shape or total_basis.shape != tscales.shape:
            raise ValueError("NFL_M2_V2D_TOTAL_FEATURE_DIMENSION_MISMATCH")
        margin_design = np.concatenate(([1.0], (diff - dmeans) / dscales))
        total_design = np.concatenate(([1.0], (total_basis - tmeans) / tscales))
        margin = float(margin_design @ np.asarray(self.margin_coefficients, dtype=float))
        total = float(total_design @ np.asarray(self.total_coefficients, dtype=float))
        if not isfinite(margin) or not isfinite(total):
            raise ValueError("NFL_M2_V2D_PREDICTION_NONFINITE")
        return margin, total


@dataclass(frozen=True)
class NFLM2V2DSupportPoint:
    home_score: int
    away_score: int
    predicted_margin: float
    predicted_total: float


@dataclass(frozen=True)
class NFLM2V2DCandidateModel:
    model_id: str
    feature_contract: str
    distribution_contract: str
    mean_model: NFLM2V2DMeanModel
    support_points: tuple[NFLM2V2DSupportPoint, ...]
    train_seasons: tuple[int, ...]
    margin_kernel_scale: float
    total_kernel_scale: float

    def predict(self, row: dict[str, Any]) -> tuple[float, float]:
        return self.mean_model.predict(row)


def _side_vectors(row: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    home = row.get("home_features")
    away = row.get("away_features")
    if not isinstance(home, dict) or not isinstance(away, dict):
        raise ValueError("NFL_M2_V2D_GAME_FEATURES_REQUIRED")
    home_v = np.asarray(_validated_feature_vector(home, "home"), dtype=float)
    away_v = np.asarray(_validated_feature_vector(away, "away"), dtype=float)
    if home_v.shape != away_v.shape:
        raise ValueError("NFL_M2_V2D_SIDE_FEATURE_DIMENSION_MISMATCH")
    return home_v, away_v


def _structured_basis(row: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    home, away = _side_vectors(row)
    diff = home - away
    shared = 0.5 * (home + away)
    absolute_matchup = np.abs(diff)
    total_basis = np.concatenate((shared, absolute_matchup))
    return diff, total_basis


def _scale_matrix(matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    means = matrix.mean(axis=0)
    scales = matrix.std(axis=0)
    scales = np.where(scales > 1e-12, scales, 1.0)
    standardized = (matrix - means) / scales
    return standardized, means, scales


def fit_nfl_m2_v2d_candidate(
    rows: Iterable[dict[str, Any]],
    *,
    ridge_alpha: float = 10.0,
    margin_kernel_scale: float = 1.0,
    total_kernel_scale: float = 1.0,
) -> NFLM2V2DCandidateModel:
    data = [dict(row) for row in rows]
    if len(data) < 2:
        raise ValueError("NFL_M2_V2D_TRAINING_ROWS_INSUFFICIENT")
    alpha = float(ridge_alpha)
    margin_scale = float(margin_kernel_scale)
    total_scale = float(total_kernel_scale)
    if not isfinite(alpha) or alpha < 0.0:
        raise ValueError("NFL_M2_V2D_RIDGE_ALPHA_INVALID")
    if not isfinite(margin_scale) or margin_scale <= 0.0:
        raise ValueError("NFL_M2_V2D_MARGIN_KERNEL_SCALE_INVALID")
    if not isfinite(total_scale) or total_scale <= 0.0:
        raise ValueError("NFL_M2_V2D_TOTAL_KERNEL_SCALE_INVALID")

    bases = [_structured_basis(row) for row in data]
    diff_x = np.asarray([basis[0] for basis in bases], dtype=float)
    total_x = np.asarray([basis[1] for basis in bases], dtype=float)
    diff_z, diff_means, diff_scales = _scale_matrix(diff_x)
    total_z, total_means, total_scales = _scale_matrix(total_x)
    margin_design = np.column_stack((np.ones(len(data), dtype=float), diff_z))
    total_design = np.column_stack((np.ones(len(data), dtype=float), total_z))

    targets = [_target_scores(row) for row in data]
    margin_y = np.asarray([target[0] for target in targets], dtype=float)
    total_y = np.asarray([target[1] for target in targets], dtype=float)
    margin_coef = _ridge_coefficients(margin_design, margin_y, alpha)
    total_coef = _ridge_coefficients(total_design, total_y, alpha)
    margin_residual = margin_y - margin_design @ margin_coef
    total_residual = total_y - total_design @ total_coef
    margin_sigma = float(sqrt(float(np.mean(margin_residual ** 2))))
    total_sigma = float(sqrt(float(np.mean(total_residual ** 2))))
    if margin_sigma <= 1e-12 or total_sigma <= 1e-12:
        raise ValueError("NFL_M2_V2D_RESIDUAL_SIGMA_ZERO")

    seasons = tuple(sorted({int(row["season"]) for row in data}))
    feature_names = tuple(str(name) for name in _MODEL_FEATURES)
    mean_model = NFLM2V2DMeanModel(
        feature_contract=NFL_M2_FEATURE_CONTRACT,
        feature_names=feature_names,
        diff_means=tuple(float(value) for value in diff_means.tolist()),
        diff_scales=tuple(float(value) for value in diff_scales.tolist()),
        total_means=tuple(float(value) for value in total_means.tolist()),
        total_scales=tuple(float(value) for value in total_scales.tolist()),
        margin_coefficients=tuple(float(value) for value in margin_coef.tolist()),
        total_coefficients=tuple(float(value) for value in total_coef.tolist()),
        train_seasons=seasons,
        ridge_alpha=alpha,
        margin_sigma=margin_sigma,
        total_sigma=total_sigma,
    )

    support: list[NFLM2V2DSupportPoint] = []
    for row in data:
        home = _integer_score(row.get("home_score"), "HOME_SCORE")
        away = _integer_score(row.get("away_score"), "AWAY_SCORE")
        predicted_margin, predicted_total = mean_model.predict(row)
        support.append(NFLM2V2DSupportPoint(
            home_score=home,
            away_score=away,
            predicted_margin=float(predicted_margin),
            predicted_total=float(predicted_total),
        ))

    return NFLM2V2DCandidateModel(
        model_id=NFL_M2_V2D_CANDIDATE_MODEL_ID,
        feature_contract=NFL_M2_FEATURE_CONTRACT,
        distribution_contract=NFL_M2_V2D_DISTRIBUTION_CONTRACT,
        mean_model=mean_model,
        support_points=tuple(support),
        train_seasons=seasons,
        margin_kernel_scale=margin_scale,
        total_kernel_scale=total_scale,
    )


def derive_nfl_m2_v2d_score_distribution(
    model: NFLM2V2DCandidateModel,
    row: dict[str, Any],
) -> tuple[dict[str, float | int], ...]:
    if model.model_id != NFL_M2_V2D_CANDIDATE_MODEL_ID:
        raise ValueError("NFL_M2_V2D_MODEL_IDENTITY_INVALID")
    if model.feature_contract != NFL_M2_FEATURE_CONTRACT:
        raise ValueError("NFL_M2_V2D_FEATURE_CONTRACT_INVALID")
    if model.distribution_contract != NFL_M2_V2D_DISTRIBUTION_CONTRACT:
        raise ValueError("NFL_M2_V2D_DISTRIBUTION_CONTRACT_INVALID")
    if not model.support_points:
        raise ValueError("NFL_M2_V2D_SUPPORT_EMPTY")

    target_margin, target_total = model.predict(dict(row))
    margin_bw = model.mean_model.margin_sigma * model.margin_kernel_scale
    total_bw = model.mean_model.total_sigma * model.total_kernel_scale
    if margin_bw <= 0.0 or total_bw <= 0.0:
        raise ValueError("NFL_M2_V2D_BANDWIDTH_INVALID")

    log_weights: list[float] = []
    for point in model.support_points:
        dm = (point.predicted_margin - target_margin) / margin_bw
        dt = (point.predicted_total - target_total) / total_bw
        log_weights.append(-0.5 * (dm * dm + dt * dt))
    anchor = max(log_weights)
    raw_weights = [exp(value - anchor) for value in log_weights]
    denominator = sum(raw_weights)
    if not isfinite(denominator) or denominator <= 0.0:
        raise ValueError("NFL_M2_V2D_WEIGHT_NORMALIZATION_FAILED")

    aggregated: dict[tuple[int, int], float] = {}
    for point, weight in zip(model.support_points, raw_weights):
        key = (point.home_score, point.away_score)
        aggregated[key] = aggregated.get(key, 0.0) + weight / denominator
    norm = sum(aggregated.values())
    if not isfinite(norm) or norm <= 0.0:
        raise ValueError("NFL_M2_V2D_AGGREGATED_WEIGHT_INVALID")
    distribution = tuple(
        {
            "home_score": home,
            "away_score": away,
            "margin": home - away,
            "total": home + away,
            "weight": weight / norm,
        }
        for (home, away), weight in sorted(aggregated.items())
    )
    if abs(sum(float(row["weight"]) for row in distribution) - 1.0) > 1e-10:
        raise ValueError("NFL_M2_V2D_WEIGHT_CONSERVATION_FAILED")
    return distribution
