"""NFL M2 V2C diagnostic: translate training score residuals to target state.

This candidate is diagnostic-only. It reuses the exact market-blind V1 ridge mean
model, learns only home/away scoring residuals from training games, translates
those residuals to the held-out game's predicted scoring state, and rounds back to
nonnegative integer scores. No sportsbook field, historical key-number target, or
held-out outcome is consumed by the fit or distribution.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Iterable

from .m2 import NFLM2ScoreModel, NFL_M2_FEATURE_CONTRACT, fit_nfl_m2_score_model
from .m2_v2_candidate import _integer_score

NFL_M2_V2C_CANDIDATE_MODEL_ID = "nfl_m2_residual_translation_v2c_candidate"
NFL_M2_V2C_DISTRIBUTION_CONTRACT = "NFL_M2_V2C_TRAINING_RESIDUAL_TRANSLATION_V1"


@dataclass(frozen=True)
class NFLM2V2CResidual:
    home_residual: float
    away_residual: float


@dataclass(frozen=True)
class NFLM2V2CCandidateModel:
    model_id: str
    feature_contract: str
    distribution_contract: str
    mean_model: NFLM2ScoreModel
    residuals: tuple[NFLM2V2CResidual, ...]
    train_seasons: tuple[int, ...]

    def predict(self, row: dict[str, Any]) -> tuple[float, float]:
        return self.mean_model.predict(row)


def _score_means(margin: float, total: float) -> tuple[float, float]:
    home = max(0.0, 0.5 * (float(total) + float(margin)))
    away = max(0.0, 0.5 * (float(total) - float(margin)))
    if not isfinite(home) or not isfinite(away):
        raise ValueError("NFL_M2_V2C_SCORE_MEAN_NONFINITE")
    return home, away


def fit_nfl_m2_v2c_candidate(
    rows: Iterable[dict[str, Any]],
    *,
    ridge_alpha: float = 10.0,
) -> NFLM2V2CCandidateModel:
    data = [dict(row) for row in rows]
    if len(data) < 2:
        raise ValueError("NFL_M2_V2C_TRAINING_ROWS_INSUFFICIENT")
    mean_model = fit_nfl_m2_score_model(data, ridge_alpha=ridge_alpha)
    if mean_model.feature_contract != NFL_M2_FEATURE_CONTRACT:
        raise ValueError("NFL_M2_V2C_FEATURE_CONTRACT_MISMATCH")

    residuals: list[NFLM2V2CResidual] = []
    for row in data:
        observed_home = _integer_score(row.get("home_score"), "HOME_SCORE")
        observed_away = _integer_score(row.get("away_score"), "AWAY_SCORE")
        predicted_margin, predicted_total = mean_model.predict(row)
        predicted_home, predicted_away = _score_means(predicted_margin, predicted_total)
        residuals.append(NFLM2V2CResidual(
            home_residual=float(observed_home) - predicted_home,
            away_residual=float(observed_away) - predicted_away,
        ))

    seasons = tuple(sorted({int(row["season"]) for row in data}))
    if seasons != mean_model.train_seasons:
        raise ValueError("NFL_M2_V2C_TRAIN_SEASON_IDENTITY_MISMATCH")
    return NFLM2V2CCandidateModel(
        model_id=NFL_M2_V2C_CANDIDATE_MODEL_ID,
        feature_contract=NFL_M2_FEATURE_CONTRACT,
        distribution_contract=NFL_M2_V2C_DISTRIBUTION_CONTRACT,
        mean_model=mean_model,
        residuals=tuple(residuals),
        train_seasons=seasons,
    )


def derive_nfl_m2_v2c_score_distribution(
    model: NFLM2V2CCandidateModel,
    row: dict[str, Any],
) -> tuple[dict[str, float | int], ...]:
    if model.model_id != NFL_M2_V2C_CANDIDATE_MODEL_ID:
        raise ValueError("NFL_M2_V2C_MODEL_IDENTITY_INVALID")
    if model.feature_contract != NFL_M2_FEATURE_CONTRACT:
        raise ValueError("NFL_M2_V2C_FEATURE_CONTRACT_INVALID")
    if model.distribution_contract != NFL_M2_V2C_DISTRIBUTION_CONTRACT:
        raise ValueError("NFL_M2_V2C_DISTRIBUTION_CONTRACT_INVALID")
    if not model.residuals:
        raise ValueError("NFL_M2_V2C_RESIDUAL_SUPPORT_EMPTY")

    target_margin, target_total = model.predict(dict(row))
    target_home, target_away = _score_means(target_margin, target_total)
    counts: dict[tuple[int, int], int] = {}
    for residual in model.residuals:
        home = max(0, int(round(target_home + residual.home_residual)))
        away = max(0, int(round(target_away + residual.away_residual)))
        counts[(home, away)] = counts.get((home, away), 0) + 1

    denominator = sum(counts.values())
    if denominator <= 0:
        raise ValueError("NFL_M2_V2C_WEIGHT_NORMALIZATION_FAILED")
    distribution = tuple(
        {
            "home_score": home,
            "away_score": away,
            "margin": home - away,
            "total": home + away,
            "weight": count / float(denominator),
        }
        for (home, away), count in sorted(counts.items())
    )
    if abs(sum(float(item["weight"]) for item in distribution) - 1.0) > 1e-10:
        raise ValueError("NFL_M2_V2C_WEIGHT_CONSERVATION_FAILED")
    return distribution
