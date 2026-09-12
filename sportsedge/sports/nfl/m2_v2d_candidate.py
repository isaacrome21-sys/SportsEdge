"""NFL M2 V2D diagnostic: direct home/away score conditional means.

V2D changes the target representation rather than tuning the V1/V2C
margin/total ridge path. It retains the exact market-blind M2 feature contract,
fits home and away scores independently, and replays paired training residuals
in score space. Sportsbook data is never consumed by fit or derivation.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt
from typing import Any, Iterable

import numpy as np

from .m2 import NFL_M2_FEATURE_CONTRACT, _game_feature_vector, _ridge_coefficients

NFL_M2_V2D_CANDIDATE_MODEL_ID = "nfl_m2_direct_score_v2d_candidate"
NFL_M2_V2D_DISTRIBUTION_CONTRACT = "NFL_M2_V2D_DIRECT_SCORE_PAIRED_RESIDUAL_V1"


def _score_targets(row: dict[str, Any]) -> tuple[float, float]:
    try:
        home = float(row["home_score"])
        away = float(row["away_score"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("NFL_M2_V2D_REALIZED_SCORE_REQUIRED") from exc
    if not isfinite(home) or not isfinite(away):
        raise ValueError("NFL_M2_V2D_REALIZED_SCORE_NONFINITE")
    return home, away


def _alpha(value: Any) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("NFL_M2_V2D_RIDGE_ALPHA_INVALID") from exc
    if not isfinite(out) or out < 0.0:
        raise ValueError("NFL_M2_V2D_RIDGE_ALPHA_INVALID")
    return out


def _integer_score(value: float) -> int:
    return max(0, int(np.floor(float(value) + 0.5)))


@dataclass(frozen=True)
class NFLM2V2DCandidateModel:
    model_id: str
    feature_contract: str
    distribution_contract: str
    feature_means: tuple[float, ...]
    feature_scales: tuple[float, ...]
    home_score_coefficients: tuple[float, ...]
    away_score_coefficients: tuple[float, ...]
    train_seasons: tuple[int, ...]
    ridge_alpha: float
    home_score_sigma: float
    away_score_sigma: float
    residual_pairs: tuple[tuple[float, float], ...]

    def predict(self, row: dict[str, Any]) -> tuple[float, float]:
        raw = np.asarray(_game_feature_vector(row), dtype=float)
        means = np.asarray(self.feature_means, dtype=float)
        scales = np.asarray(self.feature_scales, dtype=float)
        if raw.shape != means.shape or raw.shape != scales.shape:
            raise ValueError("NFL_M2_V2D_FEATURE_DIMENSION_MISMATCH")
        design = np.concatenate(([1.0], (raw - means) / scales))
        home = float(design @ np.asarray(self.home_score_coefficients, dtype=float))
        away = float(design @ np.asarray(self.away_score_coefficients, dtype=float))
        if not isfinite(home) or not isfinite(away):
            raise ValueError("NFL_M2_V2D_PREDICTION_NONFINITE")
        return home, away


def fit_nfl_m2_v2d_candidate(rows: Iterable[dict[str, Any]], *, ridge_alpha: float = 10.0) -> NFLM2V2DCandidateModel:
    data = [dict(row) for row in rows]
    if len(data) < 2:
        raise ValueError("NFL_M2_V2D_TRAINING_ROWS_INSUFFICIENT")
    alpha = _alpha(ridge_alpha)
    raw_x = np.asarray([_game_feature_vector(row) for row in data], dtype=float)
    if raw_x.ndim != 2 or raw_x.shape[0] != len(data):
        raise ValueError("NFL_M2_V2D_TRAINING_MATRIX_INVALID")
    means = raw_x.mean(axis=0)
    scales = raw_x.std(axis=0)
    scales = np.where(scales > 1e-12, scales, 1.0)
    design = np.column_stack((np.ones(len(data), dtype=float), (raw_x - means) / scales))
    targets = [_score_targets(row) for row in data]
    home_y = np.asarray([target[0] for target in targets], dtype=float)
    away_y = np.asarray([target[1] for target in targets], dtype=float)
    home_coef = _ridge_coefficients(design, home_y, alpha)
    away_coef = _ridge_coefficients(design, away_y, alpha)
    home_residual = home_y - design @ home_coef
    away_residual = away_y - design @ away_coef
    home_sigma = float(sqrt(float(np.mean(home_residual ** 2))))
    away_sigma = float(sqrt(float(np.mean(away_residual ** 2))))
    if home_sigma <= 1e-12 or away_sigma <= 1e-12:
        raise ValueError("NFL_M2_V2D_RESIDUAL_SIGMA_ZERO")
    train_seasons = tuple(sorted({int(row["season"]) for row in data}))
    residual_pairs = tuple((float(home), float(away)) for home, away in zip(home_residual.tolist(), away_residual.tolist()))
    return NFLM2V2DCandidateModel(
        model_id=NFL_M2_V2D_CANDIDATE_MODEL_ID,
        feature_contract=NFL_M2_FEATURE_CONTRACT,
        distribution_contract=NFL_M2_V2D_DISTRIBUTION_CONTRACT,
        feature_means=tuple(float(value) for value in means.tolist()),
        feature_scales=tuple(float(value) for value in scales.tolist()),
        home_score_coefficients=tuple(float(value) for value in home_coef.tolist()),
        away_score_coefficients=tuple(float(value) for value in away_coef.tolist()),
        train_seasons=train_seasons,
        ridge_alpha=alpha,
        home_score_sigma=home_sigma,
        away_score_sigma=away_sigma,
        residual_pairs=residual_pairs,
    )


def derive_nfl_m2_v2d_score_distribution(model: NFLM2V2DCandidateModel, row: dict[str, Any]) -> tuple[dict[str, int], ...]:
    if model.model_id != NFL_M2_V2D_CANDIDATE_MODEL_ID:
        raise ValueError("NFL_M2_V2D_MODEL_IDENTITY_INVALID")
    if model.feature_contract != NFL_M2_FEATURE_CONTRACT:
        raise ValueError("NFL_M2_V2D_FEATURE_CONTRACT_INVALID")
    if model.distribution_contract != NFL_M2_V2D_DISTRIBUTION_CONTRACT:
        raise ValueError("NFL_M2_V2D_DISTRIBUTION_CONTRACT_INVALID")
    if not model.residual_pairs:
        raise ValueError("NFL_M2_V2D_RESIDUAL_DISTRIBUTION_MISSING")
    home_mu, away_mu = model.predict(dict(row))
    return tuple({"home_score": _integer_score(home_mu + hr), "away_score": _integer_score(away_mu + ar)} for hr, ar in model.residual_pairs)
