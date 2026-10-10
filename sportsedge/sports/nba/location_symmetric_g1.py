"""NBA symmetric location G1 research candidate.

The candidate reuses the existing PIT-safe NBATrainingRow contract. Margin is
fit only from odd-symmetric matchup differentials; total is fit only from
swap-invariant pace/efficiency features. Sportsbook data is not accepted.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable, Sequence

import numpy as np

from .simulation import NBAGameState
from .training import NBATrainingRow

MODEL_ID = "nba_location_symmetric_ridge_g1"
CANDIDATE_FAMILY = "NBA_LOCATION_SYMMETRIC_RIDGE_G1"
DEFAULT_ALPHA_GRID = (0.1, 1.0, 10.0, 100.0, 1000.0)
MARGIN_FEATURE_NAMES = (
    "offensive_rating_diff",
    "defensive_rating_advantage",
    "pace_scaled_matchup_rating_diff",
)
TOTAL_FEATURE_NAMES = (
    "expected_possessions",
    "matchup_efficiency_sum",
    "pace_scaled_matchup_efficiency_sum",
)


class NBASymmetricLocationError(ValueError):
    pass


def season_end_year(row: NBATrainingRow) -> int:
    row.validate()
    return row.tipoff.year + 1 if row.tipoff.month >= 7 else row.tipoff.year


def margin_feature_vector(row: NBATrainingRow) -> np.ndarray:
    row.validate()
    offense_diff = row.home_offensive_rating - row.away_offensive_rating
    defense_adv = row.away_defensive_rating - row.home_defensive_rating
    matchup_diff = 0.5 * (offense_diff + defense_adv)
    return np.asarray(
        (
            offense_diff,
            defense_adv,
            row.expected_possessions * matchup_diff / 100.0,
        ),
        dtype=float,
    )


def total_feature_vector(row: NBATrainingRow) -> np.ndarray:
    row.validate()
    # Expected per-100 matchup scoring: each offense blended with opposing defense.
    home_matchup = 0.5 * (row.home_offensive_rating + row.away_defensive_rating)
    away_matchup = 0.5 * (row.away_offensive_rating + row.home_defensive_rating)
    efficiency_sum = home_matchup + away_matchup
    return np.asarray(
        (
            row.expected_possessions,
            efficiency_sum,
            row.expected_possessions * efficiency_sum / 100.0,
        ),
        dtype=float,
    )


def _target(row: NBATrainingRow, target: str) -> float:
    row.validate()
    if target == "margin":
        return float(row.home_points - row.away_points)
    if target == "total":
        return float(row.home_points + row.away_points)
    raise NBASymmetricLocationError(f"NBA_LOCATION_G1_TARGET_UNSUPPORTED:{target}")


def _ridge_coefficients(design: np.ndarray, y: np.ndarray, alpha: float) -> np.ndarray:
    penalty = np.eye(design.shape[1], dtype=float) * float(alpha)
    penalty[0, 0] = 0.0
    lhs = design.T @ design + penalty
    rhs = design.T @ y
    try:
        return np.linalg.solve(lhs, rhs)
    except np.linalg.LinAlgError:
        return np.linalg.pinv(lhs) @ rhs


@dataclass(frozen=True)
class _Component:
    means: tuple[float, ...]
    scales: tuple[float, ...]
    coefficients: tuple[float, ...]
    alpha: float


def _fit_component(rows: Sequence[NBATrainingRow], *, target: str, alpha: float) -> _Component:
    data = tuple(rows)
    if len(data) < 2:
        raise NBASymmetricLocationError("NBA_LOCATION_G1_TRAINING_ROWS_INSUFFICIENT")
    a = float(alpha)
    if not isfinite(a) or a < 0:
        raise NBASymmetricLocationError("NBA_LOCATION_G1_ALPHA_INVALID")
    vector = margin_feature_vector if target == "margin" else total_feature_vector
    x = np.asarray([vector(row) for row in data], dtype=float)
    means = x.mean(axis=0)
    scales = x.std(axis=0)
    scales = np.where(scales > 1e-12, scales, 1.0)
    design = np.column_stack((np.ones(len(data)), (x - means) / scales))
    y = np.asarray([_target(row, target) for row in data], dtype=float)
    beta = _ridge_coefficients(design, y, a)
    return _Component(
        tuple(float(v) for v in means),
        tuple(float(v) for v in scales),
        tuple(float(v) for v in beta),
        a,
    )


def _predict(component: _Component, row: NBATrainingRow, *, target: str) -> float:
    raw = margin_feature_vector(row) if target == "margin" else total_feature_vector(row)
    means = np.asarray(component.means)
    scales = np.asarray(component.scales)
    design = np.concatenate(([1.0], (raw - means) / scales))
    value = float(design @ np.asarray(component.coefficients))
    if not isfinite(value):
        raise NBASymmetricLocationError("NBA_LOCATION_G1_PREDICTION_NONFINITE")
    return value


def _season_groups(rows: Sequence[NBATrainingRow]) -> tuple[int, ...]:
    return tuple(sorted({season_end_year(row) for row in rows}))


def select_alpha(
    rows: Iterable[NBATrainingRow],
    *,
    target: str,
    alpha_grid: Sequence[float] = DEFAULT_ALPHA_GRID,
    min_train_seasons: int = 2,
) -> dict:
    data = tuple(sorted(rows, key=lambda r: (r.tipoff, r.game_id)))
    seasons = _season_groups(data)
    if len(seasons) <= min_train_seasons:
        raise NBASymmetricLocationError("NBA_LOCATION_G1_INNER_FOLDS_REQUIRED")
    candidates = []
    for alpha in tuple(float(v) for v in alpha_grid):
        sq = 0.0
        n = 0
        folds = []
        for idx in range(min_train_seasons, len(seasons)):
            test_season = seasons[idx]
            train_seasons = seasons[:idx]
            train = tuple(r for r in data if season_end_year(r) in train_seasons)
            test = tuple(r for r in data if season_end_year(r) == test_season)
            fit = _fit_component(train, target=target, alpha=alpha)
            errors = [_predict(fit, row, target=target) - _target(row, target) for row in test]
            if errors:
                fold_rmse = (sum(e * e for e in errors) / len(errors)) ** 0.5
                folds.append({"test_season": test_season, "train_seasons": list(train_seasons), "rmse": fold_rmse, "n": len(errors)})
                sq += sum(e * e for e in errors)
                n += len(errors)
        if n <= 0:
            raise NBASymmetricLocationError("NBA_LOCATION_G1_INNER_SCORING_EMPTY")
        candidates.append({"alpha": alpha, "rmse": (sq / n) ** 0.5, "n": n, "folds": folds})
    selected = min(candidates, key=lambda r: (float(r["rmse"]), -float(r["alpha"])))
    return {"target": target, "selected_alpha": selected["alpha"], "candidates": candidates}


@dataclass(frozen=True)
class NBASymmetricLocationG1:
    margin: _Component
    total: _Component
    train_seasons: tuple[int, ...]
    model_id: str = MODEL_ID
    candidate_family: str = CANDIDATE_FAMILY

    def predict(self, row: NBATrainingRow) -> tuple[float, float]:
        return _predict(self.margin, row, target="margin"), _predict(self.total, row, target="total")


def fit_nba_location_symmetric_g1(
    rows: Iterable[NBATrainingRow],
    *,
    margin_alpha: float,
    total_alpha: float,
) -> NBASymmetricLocationG1:
    data = tuple(sorted(rows, key=lambda r: (r.tipoff, r.game_id)))
    if len(data) < 2:
        raise NBASymmetricLocationError("NBA_LOCATION_G1_TRAINING_ROWS_INSUFFICIENT")
    return NBASymmetricLocationG1(
        margin=_fit_component(data, target="margin", alpha=margin_alpha),
        total=_fit_component(data, target="total", alpha=total_alpha),
        train_seasons=_season_groups(data),
    )


def game_state_from_location(
    model: NBASymmetricLocationG1,
    row: NBATrainingRow,
) -> NBAGameState:
    margin, total = model.predict(row)
    home_points = 0.5 * (total + margin)
    away_points = 0.5 * (total - margin)
    if home_points <= 0 or away_points <= 0 or row.expected_possessions <= 0:
        raise NBASymmetricLocationError("NBA_LOCATION_G1_TEAM_POINTS_NONPOSITIVE")
    return NBAGameState(
        game_id=row.game_id,
        expected_possessions=row.expected_possessions,
        home_points_per_100=100.0 * home_points / row.expected_possessions,
        away_points_per_100=100.0 * away_points / row.expected_possessions,
    )


__all__ = [
    "CANDIDATE_FAMILY",
    "DEFAULT_ALPHA_GRID",
    "MARGIN_FEATURE_NAMES",
    "MODEL_ID",
    "NBASymmetricLocationError",
    "NBASymmetricLocationG1",
    "TOTAL_FEATURE_NAMES",
    "fit_nba_location_symmetric_g1",
    "game_state_from_location",
    "margin_feature_vector",
    "season_end_year",
    "select_alpha",
    "total_feature_vector",
]
