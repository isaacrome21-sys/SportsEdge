"""NFL M2 V2 candidate: training-only empirical integer score support.

This is a diagnostic candidate, not a production model and not promotion evidence.
It deliberately reuses the exact V1 market-blind mean model so Phase A changes only
the conditional score-distribution layer. Every support point is an actually
observed integer training score pair. Held-out games weight those support points
by similarity between training-predicted and held-out-predicted margin/total state.
No sportsbook line, price, historical key-number target, or held-out outcome enters
the fit or distribution.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite
from typing import Any, Iterable

from .m2 import (
    NFLM2ScoreModel,
    NFL_M2_FEATURE_CONTRACT,
    fit_nfl_m2_score_model,
)

NFL_M2_V2_CANDIDATE_MODEL_ID = "nfl_m2_discrete_score_support_v2_candidate"
NFL_M2_V2_DISTRIBUTION_CONTRACT = "NFL_M2_V2_TRAINING_EMPIRICAL_SCORE_SUPPORT_V1"


@dataclass(frozen=True)
class NFLM2V2SupportPoint:
    home_score: int
    away_score: int
    predicted_margin: float
    predicted_total: float

    @property
    def margin(self) -> int:
        return self.home_score - self.away_score

    @property
    def total(self) -> int:
        return self.home_score + self.away_score


@dataclass(frozen=True)
class NFLM2V2CandidateModel:
    model_id: str
    feature_contract: str
    distribution_contract: str
    mean_model: NFLM2ScoreModel
    support_points: tuple[NFLM2V2SupportPoint, ...]
    train_seasons: tuple[int, ...]
    kernel_scale: float
    margin_kernel_scale: float
    total_kernel_scale: float

    def predict(self, row: dict[str, Any]) -> tuple[float, float]:
        return self.mean_model.predict(row)


def _integer_score(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"NFL_M2_V2_{field}_INTEGER_REQUIRED")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"NFL_M2_V2_{field}_INTEGER_REQUIRED") from exc
    if not isfinite(number) or number < 0 or abs(number - round(number)) > 1e-12:
        raise ValueError(f"NFL_M2_V2_{field}_INTEGER_REQUIRED")
    return int(round(number))


def _positive_scale(value: Any, field: str) -> float:
    try:
        scale = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"NFL_M2_V2_{field}_INVALID") from exc
    if not isfinite(scale) or scale <= 0.0:
        raise ValueError(f"NFL_M2_V2_{field}_INVALID")
    return scale


def fit_nfl_m2_v2_candidate(
    rows: Iterable[dict[str, Any]],
    *,
    ridge_alpha: float = 10.0,
    kernel_scale: float = 1.0,
    margin_kernel_scale: float | None = None,
    total_kernel_scale: float | None = None,
) -> NFLM2V2CandidateModel:
    """Fit the isolated V2 score-support candidate on training rows only.

    ``kernel_scale`` is retained as the backwards-compatible shared default.
    Optional dimension-specific scales allow a diagnostic training-only selector
    to tune margin and total smoothing independently without changing production.
    """
    data = [dict(row) for row in rows]
    if len(data) < 2:
        raise ValueError("NFL_M2_V2_TRAINING_ROWS_INSUFFICIENT")
    scale = _positive_scale(kernel_scale, "KERNEL_SCALE")
    margin_scale = _positive_scale(
        scale if margin_kernel_scale is None else margin_kernel_scale,
        "MARGIN_KERNEL_SCALE",
    )
    total_scale = _positive_scale(
        scale if total_kernel_scale is None else total_kernel_scale,
        "TOTAL_KERNEL_SCALE",
    )

    # This invokes the exact production feature validation and ridge mean fit.
    # Root-level market fields are ignored by that fit, while nested market
    # contamination is already rejected by the production feature contract.
    mean_model = fit_nfl_m2_score_model(data, ridge_alpha=ridge_alpha)
    if mean_model.feature_contract != NFL_M2_FEATURE_CONTRACT:
        raise ValueError("NFL_M2_V2_FEATURE_CONTRACT_MISMATCH")

    support: list[NFLM2V2SupportPoint] = []
    for row in data:
        home = _integer_score(row.get("home_score"), "HOME_SCORE")
        away = _integer_score(row.get("away_score"), "AWAY_SCORE")
        predicted_margin, predicted_total = mean_model.predict(row)
        support.append(NFLM2V2SupportPoint(
            home_score=home,
            away_score=away,
            predicted_margin=float(predicted_margin),
            predicted_total=float(predicted_total),
        ))

    seasons = tuple(sorted({int(row["season"]) for row in data}))
    if seasons != mean_model.train_seasons:
        raise ValueError("NFL_M2_V2_TRAIN_SEASON_IDENTITY_MISMATCH")
    return NFLM2V2CandidateModel(
        model_id=NFL_M2_V2_CANDIDATE_MODEL_ID,
        feature_contract=NFL_M2_FEATURE_CONTRACT,
        distribution_contract=NFL_M2_V2_DISTRIBUTION_CONTRACT,
        mean_model=mean_model,
        support_points=tuple(support),
        train_seasons=seasons,
        kernel_scale=scale,
        margin_kernel_scale=margin_scale,
        total_kernel_scale=total_scale,
    )


def derive_nfl_m2_v2_score_distribution(
    model: NFLM2V2CandidateModel,
    row: dict[str, Any],
) -> tuple[dict[str, float | int], ...]:
    """Return a normalized weighted distribution over observed training scores."""
    if model.model_id != NFL_M2_V2_CANDIDATE_MODEL_ID:
        raise ValueError("NFL_M2_V2_MODEL_IDENTITY_INVALID")
    if model.feature_contract != NFL_M2_FEATURE_CONTRACT:
        raise ValueError("NFL_M2_V2_FEATURE_CONTRACT_INVALID")
    if model.distribution_contract != NFL_M2_V2_DISTRIBUTION_CONTRACT:
        raise ValueError("NFL_M2_V2_DISTRIBUTION_CONTRACT_INVALID")
    if not model.support_points:
        raise ValueError("NFL_M2_V2_SUPPORT_EMPTY")

    target_margin, target_total = model.predict(dict(row))
    margin_bw = float(model.mean_model.margin_sigma) * model.margin_kernel_scale
    total_bw = float(model.mean_model.total_sigma) * model.total_kernel_scale
    if margin_bw <= 0.0 or total_bw <= 0.0:
        raise ValueError("NFL_M2_V2_BANDWIDTH_INVALID")

    log_weights: list[float] = []
    for point in model.support_points:
        dm = (point.predicted_margin - target_margin) / margin_bw
        dt = (point.predicted_total - target_total) / total_bw
        log_weights.append(-0.5 * (dm * dm + dt * dt))
    anchor = max(log_weights)
    raw_weights = [exp(value - anchor) for value in log_weights]
    denominator = sum(raw_weights)
    if not isfinite(denominator) or denominator <= 0.0:
        raise ValueError("NFL_M2_V2_WEIGHT_NORMALIZATION_FAILED")

    # Aggregate repeated score pairs after weighting; deterministic ordering makes
    # artifacts and tests byte-stable without changing probability mass.
    aggregated: dict[tuple[int, int], float] = {}
    for point, raw_weight in zip(model.support_points, raw_weights):
        key = (point.home_score, point.away_score)
        aggregated[key] = aggregated.get(key, 0.0) + raw_weight / denominator

    total_weight = sum(aggregated.values())
    if not isfinite(total_weight) or total_weight <= 0.0:
        raise ValueError("NFL_M2_V2_AGGREGATED_WEIGHT_INVALID")
    rows = tuple(
        {
            "home_score": home,
            "away_score": away,
            "margin": home - away,
            "total": home + away,
            "weight": weight / total_weight,
        }
        for (home, away), weight in sorted(aggregated.items())
    )
    if abs(sum(float(item["weight"]) for item in rows) - 1.0) > 1e-10:
        raise ValueError("NFL_M2_V2_WEIGHT_CONSERVATION_FAILED")
    return rows


def price_nfl_m2_v2_game_markets(
    distribution: Iterable[dict[str, float | int]],
    *,
    spread_line: float,
    total_line: float,
) -> dict[str, dict[str, float]]:
    """Apply sportsbook thresholds only after the weighted score distribution exists."""
    rows = [dict(row) for row in distribution]
    if not rows:
        raise ValueError("NFL_M2_V2_SCORE_DISTRIBUTION_EMPTY")
    spread = float(spread_line)
    total = float(total_line)
    if not isfinite(spread) or not isfinite(total):
        raise ValueError("NFL_M2_V2_MARKET_LINE_NONFINITE")
    weights = [float(row.get("weight")) for row in rows]
    if any(not isfinite(weight) or weight < 0.0 for weight in weights):
        raise ValueError("NFL_M2_V2_DISTRIBUTION_WEIGHT_INVALID")
    weight_sum = sum(weights)
    if abs(weight_sum - 1.0) > 1e-8:
        raise ValueError("NFL_M2_V2_DISTRIBUTION_WEIGHT_NOT_NORMALIZED")

    def mass(predicate) -> float:
        return sum(weight for row, weight in zip(rows, weights) if predicate(row))

    return {
        "moneyline": {
            "home": mass(lambda row: int(row["margin"]) > 0),
            "away": mass(lambda row: int(row["margin"]) < 0),
            "tie": mass(lambda row: int(row["margin"]) == 0),
        },
        "spread": {
            "home": mass(lambda row: float(row["margin"]) + spread > 0.0),
            "away": mass(lambda row: float(row["margin"]) + spread < 0.0),
            "push": mass(lambda row: float(row["margin"]) + spread == 0.0),
        },
        "total": {
            "over": mass(lambda row: float(row["total"]) > total),
            "under": mass(lambda row: float(row["total"]) < total),
            "push": mass(lambda row: float(row["total"]) == total),
        },
    }