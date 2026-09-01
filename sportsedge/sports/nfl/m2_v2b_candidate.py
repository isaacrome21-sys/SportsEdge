"""NFL M2 V2B candidate: empirical score lattice + learned residual likelihood.

V2A proved that preserving observed integer NFL score support repairs most of the
3/7 lattice defect but its predicted-state analog weighting was not predictive
enough. V2B keeps the same market-blind V1 ridge mean model and the same empirical
integer score support, but conditions that support directly with the residual
covariance learned on the training fold.

No key number receives special treatment. No sportsbook field or held-out outcome
is consumed while building a held-out distribution.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite, log
from typing import Any, Iterable

from .m2 import NFLM2ScoreModel, NFL_M2_FEATURE_CONTRACT, fit_nfl_m2_score_model
from .m2_v2_candidate import NFLM2V2SupportPoint, _integer_score

NFL_M2_V2B_CANDIDATE_MODEL_ID = "nfl_m2_empirical_score_likelihood_v2b_candidate"
NFL_M2_V2B_DISTRIBUTION_CONTRACT = "NFL_M2_V2B_EMPIRICAL_SCORE_RESIDUAL_LIKELIHOOD_V1"


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
class NFLM2V2BCandidateModel:
    model_id: str
    feature_contract: str
    distribution_contract: str
    mean_model: NFLM2ScoreModel
    empirical_scores: tuple[NFLM2V2BEmpiricalScore, ...]
    train_seasons: tuple[int, ...]
    kernel_scale: float

    def predict(self, row: dict[str, Any]) -> tuple[float, float]:
        return self.mean_model.predict(row)


def fit_nfl_m2_v2b_candidate(
    rows: Iterable[dict[str, Any]],
    *,
    ridge_alpha: float = 10.0,
    kernel_scale: float = 1.0,
) -> NFLM2V2BCandidateModel:
    data = [dict(row) for row in rows]
    if len(data) < 2:
        raise ValueError("NFL_M2_V2B_TRAINING_ROWS_INSUFFICIENT")
    scale = float(kernel_scale)
    if not isfinite(scale) or scale <= 0.0:
        raise ValueError("NFL_M2_V2B_KERNEL_SCALE_INVALID")
    mean_model = fit_nfl_m2_score_model(data, ridge_alpha=ridge_alpha)
    if mean_model.feature_contract != NFL_M2_FEATURE_CONTRACT:
        raise ValueError("NFL_M2_V2B_FEATURE_CONTRACT_MISMATCH")

    counts: dict[tuple[int, int], int] = {}
    for row in data:
        home = _integer_score(row.get("home_score"), "HOME_SCORE")
        away = _integer_score(row.get("away_score"), "AWAY_SCORE")
        counts[(home, away)] = counts.get((home, away), 0) + 1
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
        train_seasons=seasons,
        kernel_scale=scale,
    )


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

    margin_mu, total_mu = model.predict(dict(row))
    margin_sigma = float(model.mean_model.margin_sigma) * model.kernel_scale
    total_sigma = float(model.mean_model.total_sigma) * model.kernel_scale
    if margin_sigma <= 0.0 or total_sigma <= 0.0:
        raise ValueError("NFL_M2_V2B_BANDWIDTH_INVALID")
    rho = max(-0.95, min(0.95, float(model.mean_model.residual_correlation)))
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
