"""NFL M2 V2E diagnostic: structured mean + season-crossfit score support.

V2E preserves V2D's market-blind structured mean and observed integer score-pair
support, but removes self-fit support coordinates.  A training support game in
season S is located in predicted margin/total state only by a mean model fit on
seasons strictly before S.  The held-out target game's mean is still fit on the
entire outer-training set.  No sportsbook field, key-number target, held-out
outcome, or future support season can enter support-coordinate construction.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite
from typing import Any, Iterable

from .m2 import NFL_M2_FEATURE_CONTRACT
from .m2_v2_candidate import _integer_score
from .m2_v2d_candidate import (
    NFLM2V2DMeanModel,
    fit_nfl_m2_v2d_candidate,
)

NFL_M2_V2E_CANDIDATE_MODEL_ID = "nfl_m2_structured_mean_crossfit_support_v2e_candidate"
NFL_M2_V2E_DISTRIBUTION_CONTRACT = "NFL_M2_V2E_SEASON_CROSSFIT_EMPIRICAL_SCORE_SUPPORT_V1"


@dataclass(frozen=True)
class NFLM2V2ECrossfitSupportPoint:
    home_score: int
    away_score: int
    support_season: int
    coordinate_train_seasons: tuple[int, ...]
    predicted_margin: float
    predicted_total: float

    @property
    def margin(self) -> int:
        return self.home_score - self.away_score

    @property
    def total(self) -> int:
        return self.home_score + self.away_score


@dataclass(frozen=True)
class NFLM2V2ECandidateModel:
    model_id: str
    feature_contract: str
    distribution_contract: str
    mean_model: NFLM2V2DMeanModel
    support_points: tuple[NFLM2V2ECrossfitSupportPoint, ...]
    train_seasons: tuple[int, ...]
    dropped_support_seasons: tuple[int, ...]
    margin_kernel_scale: float
    total_kernel_scale: float
    min_coordinate_train_seasons: int

    def predict(self, row: dict[str, Any]) -> tuple[float, float]:
        return self.mean_model.predict(row)


def fit_nfl_m2_v2e_candidate(
    rows: Iterable[dict[str, Any]],
    *,
    ridge_alpha: float = 10.0,
    margin_kernel_scale: float = 1.0,
    total_kernel_scale: float = 1.0,
    min_coordinate_train_seasons: int = 1,
) -> NFLM2V2ECandidateModel:
    """Fit target mean on all outer training rows and support coordinates PIT-safe."""
    data = [dict(row) for row in rows]
    if len(data) < 2:
        raise ValueError("NFL_M2_V2E_TRAINING_ROWS_INSUFFICIENT")
    margin_scale = float(margin_kernel_scale)
    total_scale = float(total_kernel_scale)
    minimum = int(min_coordinate_train_seasons)
    if not isfinite(margin_scale) or margin_scale <= 0.0:
        raise ValueError("NFL_M2_V2E_MARGIN_KERNEL_SCALE_INVALID")
    if not isfinite(total_scale) or total_scale <= 0.0:
        raise ValueError("NFL_M2_V2E_TOTAL_KERNEL_SCALE_INVALID")
    if minimum < 1:
        raise ValueError("NFL_M2_V2E_MIN_COORDINATE_TRAIN_SEASONS_INVALID")

    train_seasons = tuple(sorted({int(row["season"]) for row in data}))
    if len(train_seasons) < minimum + 1:
        raise ValueError("NFL_M2_V2E_TRAINING_SEASONS_INSUFFICIENT_FOR_CROSSFIT")

    # The target game's structured mean may use the full outer-training set.
    # Only support coordinates are cross-fit; observed support scores remain the
    # empirical integer outcome lattice.
    final_v2d = fit_nfl_m2_v2d_candidate(
        data,
        ridge_alpha=ridge_alpha,
        margin_kernel_scale=margin_scale,
        total_kernel_scale=total_scale,
    )
    final_mean = final_v2d.mean_model
    if final_mean.feature_contract != NFL_M2_FEATURE_CONTRACT:
        raise ValueError("NFL_M2_V2E_FEATURE_CONTRACT_MISMATCH")

    support: list[NFLM2V2ECrossfitSupportPoint] = []
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
        coordinate_model = fit_nfl_m2_v2d_candidate(
            prior_rows,
            ridge_alpha=ridge_alpha,
            margin_kernel_scale=margin_scale,
            total_kernel_scale=total_scale,
        ).mean_model
        if support_season in coordinate_model.train_seasons:
            raise ValueError("NFL_M2_V2E_SUPPORT_SEASON_IN_COORDINATE_TRAINING")
        if any(season >= support_season for season in coordinate_model.train_seasons):
            raise ValueError("NFL_M2_V2E_FUTURE_SUPPORT_COORDINATE_LEAKAGE")

        for row in data:
            if int(row["season"]) != support_season:
                continue
            home = _integer_score(row.get("home_score"), "HOME_SCORE")
            away = _integer_score(row.get("away_score"), "AWAY_SCORE")
            predicted_margin, predicted_total = coordinate_model.predict(row)
            support.append(NFLM2V2ECrossfitSupportPoint(
                home_score=home,
                away_score=away,
                support_season=support_season,
                coordinate_train_seasons=coordinate_model.train_seasons,
                predicted_margin=float(predicted_margin),
                predicted_total=float(predicted_total),
            ))

    if not support:
        raise ValueError("NFL_M2_V2E_CROSSFIT_SUPPORT_EMPTY")
    if any(
        point.support_season <= max(point.coordinate_train_seasons)
        for point in support
        if point.coordinate_train_seasons
    ):
        raise ValueError("NFL_M2_V2E_SUPPORT_COORDINATE_TEMPORAL_ORDER_INVALID")

    return NFLM2V2ECandidateModel(
        model_id=NFL_M2_V2E_CANDIDATE_MODEL_ID,
        feature_contract=NFL_M2_FEATURE_CONTRACT,
        distribution_contract=NFL_M2_V2E_DISTRIBUTION_CONTRACT,
        mean_model=final_mean,
        support_points=tuple(support),
        train_seasons=train_seasons,
        dropped_support_seasons=tuple(sorted(set(dropped))),
        margin_kernel_scale=margin_scale,
        total_kernel_scale=total_scale,
        min_coordinate_train_seasons=minimum,
    )


def derive_nfl_m2_v2e_score_distribution(
    model: NFLM2V2ECandidateModel,
    row: dict[str, Any],
) -> tuple[dict[str, float | int], ...]:
    """Weight PIT cross-fit observed score pairs around the held-out target mean."""
    if model.model_id != NFL_M2_V2E_CANDIDATE_MODEL_ID:
        raise ValueError("NFL_M2_V2E_MODEL_IDENTITY_INVALID")
    if model.feature_contract != NFL_M2_FEATURE_CONTRACT:
        raise ValueError("NFL_M2_V2E_FEATURE_CONTRACT_INVALID")
    if model.distribution_contract != NFL_M2_V2E_DISTRIBUTION_CONTRACT:
        raise ValueError("NFL_M2_V2E_DISTRIBUTION_CONTRACT_INVALID")
    if not model.support_points:
        raise ValueError("NFL_M2_V2E_SUPPORT_EMPTY")

    target_margin, target_total = model.predict(dict(row))
    margin_bw = float(model.mean_model.margin_sigma) * model.margin_kernel_scale
    total_bw = float(model.mean_model.total_sigma) * model.total_kernel_scale
    if margin_bw <= 0.0 or total_bw <= 0.0:
        raise ValueError("NFL_M2_V2E_BANDWIDTH_INVALID")

    log_weights: list[float] = []
    for point in model.support_points:
        dm = (point.predicted_margin - target_margin) / margin_bw
        dt = (point.predicted_total - target_total) / total_bw
        log_weights.append(-0.5 * (dm * dm + dt * dt))
    anchor = max(log_weights)
    raw_weights = [exp(value - anchor) for value in log_weights]
    denominator = sum(raw_weights)
    if not isfinite(denominator) or denominator <= 0.0:
        raise ValueError("NFL_M2_V2E_WEIGHT_NORMALIZATION_FAILED")

    aggregated: dict[tuple[int, int], float] = {}
    for point, raw_weight in zip(model.support_points, raw_weights):
        key = (point.home_score, point.away_score)
        aggregated[key] = aggregated.get(key, 0.0) + raw_weight / denominator
    norm = sum(aggregated.values())
    if not isfinite(norm) or norm <= 0.0:
        raise ValueError("NFL_M2_V2E_AGGREGATED_WEIGHT_INVALID")
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
        raise ValueError("NFL_M2_V2E_WEIGHT_CONSERVATION_FAILED")
    return distribution
