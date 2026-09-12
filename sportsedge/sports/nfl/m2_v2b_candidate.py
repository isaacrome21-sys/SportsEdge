"""NFL M2 V2B candidate: empirical score lattice + local residual likelihood.

V2A proved that preserving observed integer NFL score support repairs most of the
3/7 lattice defect but its predicted-state analog weighting was not predictive
enough. V2B keeps the same market-blind V1 ridge mean model and empirical integer
score support, then estimates local residual location and dispersion from training
rows near the target predicted game state. The local covariance is shrunk toward
the global training-fold covariance using effective local sample size so sparse
neighborhoods cannot create unstable certainty.

No key number receives special treatment. No sportsbook field or held-out outcome
is consumed while building a held-out distribution.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite, log, sqrt
from typing import Any, Iterable

from .m2 import NFLM2ScoreModel, NFL_M2_FEATURE_CONTRACT, fit_nfl_m2_score_model
from .m2_v2_candidate import _integer_score

NFL_M2_V2B_CANDIDATE_MODEL_ID = "nfl_m2_empirical_score_likelihood_v2b_candidate"
NFL_M2_V2B_DISTRIBUTION_CONTRACT = "NFL_M2_V2B_EMPIRICAL_SCORE_LOCAL_RESIDUAL_LIKELIHOOD_V3"
DEFAULT_NEIGHBORHOOD_SCALE = 1.0
DEFAULT_COVARIANCE_SHRINKAGE_N = 25.0


@dataclass(frozen=True)
class NFLM2V2BEmpiricalScore:
    home_score: int
    away_score: int
    count: int

    @property
    def margin(self) -> int:
        return self.home_score - self.away_score

    @property
    def total(self) -> int:
        return self.home_score + self.away_score


@dataclass(frozen=True)
class NFLM2V2BResidualPoint:
    predicted_margin: float
    predicted_total: float
    margin_residual: float
    total_residual: float


@dataclass(frozen=True)
class NFLM2V2BCandidateModel:
    model_id: str
    feature_contract: str
    distribution_contract: str
    mean_model: NFLM2ScoreModel
    empirical_scores: tuple[NFLM2V2BEmpiricalScore, ...]
    residual_points: tuple[NFLM2V2BResidualPoint, ...]
    train_seasons: tuple[int, ...]
    kernel_scale: float
    neighborhood_scale: float
    covariance_shrinkage_n: float

    def predict(self, row: dict[str, Any]) -> tuple[float, float]:
        return self.mean_model.predict(row)


def fit_nfl_m2_v2b_candidate(
    rows: Iterable[dict[str, Any]],
    *,
    ridge_alpha: float = 10.0,
    kernel_scale: float = 1.0,
    neighborhood_scale: float = DEFAULT_NEIGHBORHOOD_SCALE,
    covariance_shrinkage_n: float = DEFAULT_COVARIANCE_SHRINKAGE_N,
) -> NFLM2V2BCandidateModel:
    data = [dict(row) for row in rows]
    if len(data) < 2:
        raise ValueError("NFL_M2_V2B_TRAINING_ROWS_INSUFFICIENT")
    scale = float(kernel_scale)
    neighborhood = float(neighborhood_scale)
    shrinkage_n = float(covariance_shrinkage_n)
    if not isfinite(scale) or scale <= 0.0:
        raise ValueError("NFL_M2_V2B_KERNEL_SCALE_INVALID")
    if not isfinite(neighborhood) or neighborhood <= 0.0:
        raise ValueError("NFL_M2_V2B_NEIGHBORHOOD_SCALE_INVALID")
    if not isfinite(shrinkage_n) or shrinkage_n <= 0.0:
        raise ValueError("NFL_M2_V2B_COVARIANCE_SHRINKAGE_INVALID")
    mean_model = fit_nfl_m2_score_model(data, ridge_alpha=ridge_alpha)
    if mean_model.feature_contract != NFL_M2_FEATURE_CONTRACT:
        raise ValueError("NFL_M2_V2B_FEATURE_CONTRACT_MISMATCH")

    counts: dict[tuple[int, int], int] = {}
    residual_points: list[NFLM2V2BResidualPoint] = []
    for row in data:
        home = _integer_score(row.get("home_score"), "HOME_SCORE")
        away = _integer_score(row.get("away_score"), "AWAY_SCORE")
        counts[(home, away)] = counts.get((home, away), 0) + 1
        predicted_margin, predicted_total = mean_model.predict(row)
        residual_points.append(
            NFLM2V2BResidualPoint(
                predicted_margin=float(predicted_margin),
                predicted_total=float(predicted_total),
                margin_residual=float((home - away) - predicted_margin),
                total_residual=float((home + away) - predicted_total),
            )
        )
    scores = tuple(
        NFLM2V2BEmpiricalScore(home, away, count)
        for (home, away), count in sorted(counts.items())
    )
    seasons = tuple(sorted({int(row["season"]) for row in data}))
    if seasons != mean_model.train_seasons:
        raise ValueError("NFL_M2_V2B_TRAIN_SEASON_IDENTITY_MISMATCH")
    return NFLM2V2BCandidateModel(
        model_id=NFL_M2_V2B_CANDIDATE_MODEL_ID,
        feature_contract=NFL_M2_FEATURE_CONTRACT,
        distribution_contract=NFL_M2_V2B_DISTRIBUTION_CONTRACT,
        mean_model=mean_model,
        empirical_scores=scores,
        residual_points=tuple(residual_points),
        train_seasons=seasons,
        kernel_scale=scale,
        neighborhood_scale=neighborhood,
        covariance_shrinkage_n=shrinkage_n,
    )


def _local_residual_parameters(
    model: NFLM2V2BCandidateModel,
    *,
    margin_mu: float,
    total_mu: float,
) -> tuple[float, float, float, float, float, float]:
    """Return local residual means, shrunk sigmas, rho, and effective N.

    Every quantity is estimated from training residual points only. Local residual
    means are shrunk toward zero using the same effective-sample-size rule used for
    covariance shrinkage, preventing sparse neighborhoods from creating large
    unregularized location corrections.
    """
    if not model.residual_points:
        raise ValueError("NFL_M2_V2B_RESIDUAL_POINTS_EMPTY")
    global_margin_sigma = float(model.mean_model.margin_sigma)
    global_total_sigma = float(model.mean_model.total_sigma)
    global_rho = max(-0.95, min(0.95, float(model.mean_model.residual_correlation)))
    if global_margin_sigma <= 0.0 or global_total_sigma <= 0.0:
        raise ValueError("NFL_M2_V2B_GLOBAL_COVARIANCE_INVALID")

    raw_weights: list[float] = []
    neighborhood = model.neighborhood_scale
    for point in model.residual_points:
        dm = (point.predicted_margin - margin_mu) / (global_margin_sigma * neighborhood)
        dt = (point.predicted_total - total_mu) / (global_total_sigma * neighborhood)
        raw_weights.append(exp(-0.5 * (dm * dm + dt * dt)))
    weight_sum = sum(raw_weights)
    if not isfinite(weight_sum) or weight_sum <= 0.0:
        raise ValueError("NFL_M2_V2B_LOCAL_WEIGHT_NORMALIZATION_FAILED")
    weights = [weight / weight_sum for weight in raw_weights]
    weight_sq_sum = sum(weight * weight for weight in weights)
    if weight_sq_sum <= 0.0:
        raise ValueError("NFL_M2_V2B_LOCAL_EFFECTIVE_N_INVALID")
    effective_n = 1.0 / weight_sq_sum

    local_margin_mean = sum(
        weight * point.margin_residual
        for weight, point in zip(weights, model.residual_points)
    )
    local_total_mean = sum(
        weight * point.total_residual
        for weight, point in zip(weights, model.residual_points)
    )
    local_margin_var = sum(
        weight * (point.margin_residual - local_margin_mean) ** 2
        for weight, point in zip(weights, model.residual_points)
    )
    local_total_var = sum(
        weight * (point.total_residual - local_total_mean) ** 2
        for weight, point in zip(weights, model.residual_points)
    )
    local_cov = sum(
        weight
        * (point.margin_residual - local_margin_mean)
        * (point.total_residual - local_total_mean)
        for weight, point in zip(weights, model.residual_points)
    )

    global_margin_var = global_margin_sigma * global_margin_sigma
    global_total_var = global_total_sigma * global_total_sigma
    global_cov = global_rho * global_margin_sigma * global_total_sigma
    local_weight = effective_n / (effective_n + model.covariance_shrinkage_n)
    margin_var = local_weight * local_margin_var + (1.0 - local_weight) * global_margin_var
    total_var = local_weight * local_total_var + (1.0 - local_weight) * global_total_var
    covariance = local_weight * local_cov + (1.0 - local_weight) * global_cov
    if margin_var <= 0.0 or total_var <= 0.0:
        raise ValueError("NFL_M2_V2B_LOCAL_COVARIANCE_INVALID")
    margin_sigma = sqrt(margin_var) * model.kernel_scale
    total_sigma = sqrt(total_var) * model.kernel_scale
    rho = covariance / sqrt(margin_var * total_var)
    rho = max(-0.95, min(0.95, rho))
    margin_bias = local_weight * local_margin_mean
    total_bias = local_weight * local_total_mean
    if not all(isfinite(value) for value in (margin_bias, total_bias, margin_sigma, total_sigma, rho, effective_n)):
        raise ValueError("NFL_M2_V2B_LOCAL_PARAMETERS_NONFINITE")
    return margin_bias, total_bias, margin_sigma, total_sigma, rho, effective_n


def derive_nfl_m2_v2b_score_distribution(
    model: NFLM2V2BCandidateModel,
    row: dict[str, Any],
) -> tuple[dict[str, float | int], ...]:
    if model.model_id != NFL_M2_V2B_CANDIDATE_MODEL_ID:
        raise ValueError("NFL_M2_V2B_MODEL_IDENTITY_INVALID")
    if model.feature_contract != NFL_M2_FEATURE_CONTRACT:
        raise ValueError("NFL_M2_V2B_FEATURE_CONTRACT_INVALID")
    if model.distribution_contract != NFL_M2_V2B_DISTRIBUTION_CONTRACT:
        raise ValueError("NFL_M2_V2B_DISTRIBUTION_CONTRACT_INVALID")
    if not model.empirical_scores:
        raise ValueError("NFL_M2_V2B_EMPIRICAL_SUPPORT_EMPTY")

    raw_margin_mu, raw_total_mu = model.predict(dict(row))
    margin_bias, total_bias, margin_sigma, total_sigma, rho, _effective_n = _local_residual_parameters(
        model,
        margin_mu=raw_margin_mu,
        total_mu=raw_total_mu,
    )
    margin_mu = raw_margin_mu + margin_bias
    total_mu = raw_total_mu + total_bias
    if margin_sigma <= 0.0 or total_sigma <= 0.0:
        raise ValueError("NFL_M2_V2B_BANDWIDTH_INVALID")
    covariance_denom = 1.0 - rho * rho
    if covariance_denom <= 0.0:
        raise ValueError("NFL_M2_V2B_RESIDUAL_COVARIANCE_INVALID")

    total_count = sum(score.count for score in model.empirical_scores)
    if total_count <= 0:
        raise ValueError("NFL_M2_V2B_EMPIRICAL_COUNT_INVALID")
    log_weights: list[float] = []
    for score in model.empirical_scores:
        zm = (score.margin - margin_mu) / margin_sigma
        zt = (score.total - total_mu) / total_sigma
        mahalanobis = (zm * zm - 2.0 * rho * zm * zt + zt * zt) / covariance_denom
        base_probability = score.count / float(total_count)
        log_weights.append(log(base_probability) - 0.5 * mahalanobis)

    anchor = max(log_weights)
    raw = [exp(value - anchor) for value in log_weights]
    denominator = sum(raw)
    if not isfinite(denominator) or denominator <= 0.0:
        raise ValueError("NFL_M2_V2B_WEIGHT_NORMALIZATION_FAILED")
    distribution = tuple(
        {
            "home_score": score.home_score,
            "away_score": score.away_score,
            "margin": score.margin,
            "total": score.total,
            "weight": weight / denominator,
        }
        for score, weight in zip(model.empirical_scores, raw)
    )
    if abs(sum(float(item["weight"]) for item in distribution) - 1.0) > 1e-10:
        raise ValueError("NFL_M2_V2B_WEIGHT_CONSERVATION_FAILED")
    return distribution
