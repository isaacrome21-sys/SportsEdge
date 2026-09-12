"""NFL M2 V2F diagnostic: native team-score mean + season-crossfit support.

This file implements the frozen V2F preregistration.  It is research-only and
cannot promote or activate an NFL market.  The candidate fits home/away scoring
means from the existing market-blind M2 feature contract, locates each empirical
score-support game with models trained only on prior seasons, and weights that
support in predicted home-score/away-score space.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite, sqrt
from typing import Any, Iterable

import numpy as np

from .m2 import NFL_M2_FEATURE_CONTRACT, _ridge_coefficients, _validated_feature_vector
from .m2_v2_candidate import _integer_score

NFL_M2_V2F_CANDIDATE_MODEL_ID = "nfl_m2_native_score_mean_crossfit_support_v2f_candidate"
NFL_M2_V2F_DISTRIBUTION_CONTRACT = "NFL_M2_V2F_NATIVE_SCORE_CROSSFIT_EMPIRICAL_SUPPORT_V1"


@dataclass(frozen=True)
class NFLM2V2FMeanModel:
    feature_contract: str
    feature_dimension: int
    design_means: tuple[float, ...]
    design_scales: tuple[float, ...]
    home_coefficients: tuple[float, ...]
    away_coefficients: tuple[float, ...]
    train_seasons: tuple[int, ...]
    ridge_alpha: float
    home_sigma: float
    away_sigma: float

    def predict(self, row: dict[str, Any]) -> tuple[float, float]:
        home_design = _native_design(row, home_target=True)
        away_design = _native_design(row, home_target=False)
        means = np.asarray(self.design_means, dtype=float)
        scales = np.asarray(self.design_scales, dtype=float)
        if home_design.shape != means.shape or away_design.shape != means.shape:
            raise ValueError("NFL_M2_V2F_FEATURE_DIMENSION_MISMATCH")
        home_z = np.concatenate(([1.0], (home_design - means) / scales))
        away_z = np.concatenate(([1.0], (away_design - means) / scales))
        home = float(home_z @ np.asarray(self.home_coefficients, dtype=float))
        away = float(away_z @ np.asarray(self.away_coefficients, dtype=float))
        if not isfinite(home) or not isfinite(away):
            raise ValueError("NFL_M2_V2F_PREDICTION_NONFINITE")
        return home, away


@dataclass(frozen=True)
class NFLM2V2FSupportPoint:
    home_score: int
    away_score: int
    support_season: int
    coordinate_train_seasons: tuple[int, ...]
    predicted_home_score: float
    predicted_away_score: float


@dataclass(frozen=True)
class NFLM2V2FCandidateModel:
    model_id: str
    feature_contract: str
    distribution_contract: str
    mean_model: NFLM2V2FMeanModel
    support_points: tuple[NFLM2V2FSupportPoint, ...]
    train_seasons: tuple[int, ...]
    dropped_support_seasons: tuple[int, ...]
    home_score_kernel_scale: float
    away_score_kernel_scale: float
    min_coordinate_train_seasons: int

    def predict(self, row: dict[str, Any]) -> tuple[float, float]:
        return self.mean_model.predict(row)


def _side_vectors(row: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    home = row.get("home_features")
    away = row.get("away_features")
    if not isinstance(home, dict) or not isinstance(away, dict):
        raise ValueError("NFL_M2_V2F_GAME_FEATURES_REQUIRED")
    home_v = np.asarray(_validated_feature_vector(home, "home"), dtype=float)
    away_v = np.asarray(_validated_feature_vector(away, "away"), dtype=float)
    if home_v.shape != away_v.shape:
        raise ValueError("NFL_M2_V2F_SIDE_FEATURE_DIMENSION_MISMATCH")
    return home_v, away_v


def _native_design(row: dict[str, Any], *, home_target: bool) -> np.ndarray:
    home, away = _side_vectors(row)
    # Mirror the ordering for the away target so a single shared standardization
    # contract can represent "own team, opponent" for either side.
    return np.concatenate((home, away)) if home_target else np.concatenate((away, home))


def _fit_mean(rows: list[dict[str, Any]], *, ridge_alpha: float) -> NFLM2V2FMeanModel:
    if len(rows) < 2:
        raise ValueError("NFL_M2_V2F_TRAINING_ROWS_INSUFFICIENT")
    alpha = float(ridge_alpha)
    if not isfinite(alpha) or alpha < 0.0:
        raise ValueError("NFL_M2_V2F_RIDGE_ALPHA_INVALID")

    home_x = np.asarray([_native_design(row, home_target=True) for row in rows], dtype=float)
    away_x = np.asarray([_native_design(row, home_target=False) for row in rows], dtype=float)
    # Standardization is estimated from both mirrored training-side views only.
    pooled = np.vstack((home_x, away_x))
    means = pooled.mean(axis=0)
    scales = pooled.std(axis=0)
    scales = np.where(scales > 1e-12, scales, 1.0)
    home_design = np.column_stack((np.ones(len(rows), dtype=float), (home_x - means) / scales))
    away_design = np.column_stack((np.ones(len(rows), dtype=float), (away_x - means) / scales))

    home_y = np.asarray([float(_integer_score(row.get("home_score"), "HOME_SCORE")) for row in rows], dtype=float)
    away_y = np.asarray([float(_integer_score(row.get("away_score"), "AWAY_SCORE")) for row in rows], dtype=float)
    home_coef = _ridge_coefficients(home_design, home_y, alpha)
    away_coef = _ridge_coefficients(away_design, away_y, alpha)
    home_residual = home_y - home_design @ home_coef
    away_residual = away_y - away_design @ away_coef
    home_sigma = float(sqrt(float(np.mean(home_residual ** 2))))
    away_sigma = float(sqrt(float(np.mean(away_residual ** 2))))
    if home_sigma <= 1e-12 or away_sigma <= 1e-12:
        raise ValueError("NFL_M2_V2F_RESIDUAL_SIGMA_ZERO")

    seasons = tuple(sorted({int(row["season"]) for row in rows}))
    return NFLM2V2FMeanModel(
        feature_contract=NFL_M2_FEATURE_CONTRACT,
        feature_dimension=int(home_x.shape[1]),
        design_means=tuple(float(value) for value in means.tolist()),
        design_scales=tuple(float(value) for value in scales.tolist()),
        home_coefficients=tuple(float(value) for value in home_coef.tolist()),
        away_coefficients=tuple(float(value) for value in away_coef.tolist()),
        train_seasons=seasons,
        ridge_alpha=alpha,
        home_sigma=home_sigma,
        away_sigma=away_sigma,
    )


def fit_nfl_m2_v2f_candidate(
    rows: Iterable[dict[str, Any]],
    *,
    ridge_alpha: float = 10.0,
    home_score_kernel_scale: float = 1.0,
    away_score_kernel_scale: float = 1.0,
    min_coordinate_train_seasons: int = 1,
) -> NFLM2V2FCandidateModel:
    data = [dict(row) for row in rows]
    if len(data) < 2:
        raise ValueError("NFL_M2_V2F_TRAINING_ROWS_INSUFFICIENT")
    home_scale = float(home_score_kernel_scale)
    away_scale = float(away_score_kernel_scale)
    minimum = int(min_coordinate_train_seasons)
    if not isfinite(home_scale) or home_scale <= 0.0:
        raise ValueError("NFL_M2_V2F_HOME_KERNEL_SCALE_INVALID")
    if not isfinite(away_scale) or away_scale <= 0.0:
        raise ValueError("NFL_M2_V2F_AWAY_KERNEL_SCALE_INVALID")
    if minimum < 1:
        raise ValueError("NFL_M2_V2F_MIN_COORDINATE_TRAIN_SEASONS_INVALID")

    train_seasons = tuple(sorted({int(row["season"]) for row in data}))
    if len(train_seasons) < minimum + 1:
        raise ValueError("NFL_M2_V2F_TRAINING_SEASONS_INSUFFICIENT_FOR_CROSSFIT")
    final_mean = _fit_mean(data, ridge_alpha=ridge_alpha)

    support: list[NFLM2V2FSupportPoint] = []
    dropped: list[int] = []
    for support_season in train_seasons:
        prior_seasons = tuple(season for season in train_seasons if season < support_season)
        if len(prior_seasons) < minimum:
            dropped.append(support_season)
            continue
        prior_rows = [row for row in data if int(row["season"]) in prior_seasons]
        if len(prior_rows) < 2:
            dropped.append(support_season)
            continue
        coordinate_model = _fit_mean(prior_rows, ridge_alpha=ridge_alpha)
        if support_season in coordinate_model.train_seasons or any(
            season >= support_season for season in coordinate_model.train_seasons
        ):
            raise ValueError("NFL_M2_V2F_SUPPORT_COORDINATE_TEMPORAL_LEAKAGE")
        for row in data:
            if int(row["season"]) != support_season:
                continue
            predicted_home, predicted_away = coordinate_model.predict(row)
            support.append(NFLM2V2FSupportPoint(
                home_score=_integer_score(row.get("home_score"), "HOME_SCORE"),
                away_score=_integer_score(row.get("away_score"), "AWAY_SCORE"),
                support_season=support_season,
                coordinate_train_seasons=coordinate_model.train_seasons,
                predicted_home_score=float(predicted_home),
                predicted_away_score=float(predicted_away),
            ))

    if not support:
        raise ValueError("NFL_M2_V2F_CROSSFIT_SUPPORT_EMPTY")
    return NFLM2V2FCandidateModel(
        model_id=NFL_M2_V2F_CANDIDATE_MODEL_ID,
        feature_contract=NFL_M2_FEATURE_CONTRACT,
        distribution_contract=NFL_M2_V2F_DISTRIBUTION_CONTRACT,
        mean_model=final_mean,
        support_points=tuple(support),
        train_seasons=train_seasons,
        dropped_support_seasons=tuple(sorted(set(dropped))),
        home_score_kernel_scale=home_scale,
        away_score_kernel_scale=away_scale,
        min_coordinate_train_seasons=minimum,
    )


def derive_nfl_m2_v2f_score_distribution(
    model: NFLM2V2FCandidateModel,
    row: dict[str, Any],
) -> tuple[dict[str, float | int], ...]:
    if model.model_id != NFL_M2_V2F_CANDIDATE_MODEL_ID:
        raise ValueError("NFL_M2_V2F_MODEL_IDENTITY_INVALID")
    if model.feature_contract != NFL_M2_FEATURE_CONTRACT:
        raise ValueError("NFL_M2_V2F_FEATURE_CONTRACT_INVALID")
    if model.distribution_contract != NFL_M2_V2F_DISTRIBUTION_CONTRACT:
        raise ValueError("NFL_M2_V2F_DISTRIBUTION_CONTRACT_INVALID")
    if not model.support_points:
        raise ValueError("NFL_M2_V2F_SUPPORT_EMPTY")

    target_home, target_away = model.predict(dict(row))
    home_bw = float(model.mean_model.home_sigma) * model.home_score_kernel_scale
    away_bw = float(model.mean_model.away_sigma) * model.away_score_kernel_scale
    if home_bw <= 0.0 or away_bw <= 0.0:
        raise ValueError("NFL_M2_V2F_BANDWIDTH_INVALID")

    log_weights: list[float] = []
    for point in model.support_points:
        dh = (point.predicted_home_score - target_home) / home_bw
        da = (point.predicted_away_score - target_away) / away_bw
        log_weights.append(-0.5 * (dh * dh + da * da))
    anchor = max(log_weights)
    raw_weights = [exp(value - anchor) for value in log_weights]
    denominator = sum(raw_weights)
    if not isfinite(denominator) or denominator <= 0.0:
        raise ValueError("NFL_M2_V2F_WEIGHT_NORMALIZATION_FAILED")

    aggregated: dict[tuple[int, int], float] = {}
    for point, raw_weight in zip(model.support_points, raw_weights):
        key = (point.home_score, point.away_score)
        aggregated[key] = aggregated.get(key, 0.0) + raw_weight / denominator
    norm = sum(aggregated.values())
    if not isfinite(norm) or norm <= 0.0:
        raise ValueError("NFL_M2_V2F_AGGREGATED_WEIGHT_INVALID")
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
    if abs(sum(float(item["weight"]) for item in distribution) - 1.0) > 1e-10:
        raise ValueError("NFL_M2_V2F_WEIGHT_CONSERVATION_FAILED")
    return distribution
