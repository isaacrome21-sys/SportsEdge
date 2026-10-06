"""NFL location symmetric G1 research candidate.

G1 reuses the PIT-safe M2 feature contract but reduces the representation:
margin is modeled from home-minus-away features, while total is modeled from
symmetric sums plus game-environment features. Sportsbook fields never enter
fit or prediction.

This module has research-only authority. It does not modify or revive M2/V2K
and it does not create bettor-facing Model_P.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from sportsedge.core.walkforward.season import season_walk_forward
from sportsedge.sports.nfl.discrete_v2 import score_grid
from sportsedge.sports.nfl.m2 import (
    NFL_M2_FEATURE_CONTRACT,
    _assert_market_blind,
    _ridge_coefficients,
)

MODEL_ID = "nfl_location_symmetric_ridge_g1"
CANDIDATE_FAMILY = "NFL_LOCATION_SYMMETRIC_RIDGE_G1"
DEFAULT_ALPHA_GRID = (0.1, 1.0, 10.0, 100.0, 1000.0)

MARGIN_DIFF_KEYS = (
    "adj_off_epa",
    "adj_def_epa",
    "pass_epa",
    "rush_epa",
    "pressure_for",
    "pressure_allowed",
    "success_rate",
    "explosive_rate",
    "qb_adjustment",
    "prior_efficiency",
    "rest_diff_days",
    "travel_miles",
    "timezone_crossings",
    "short_week",
    "bye_week",
)
TOTAL_SUM_KEYS = (
    "adj_off_epa",
    "adj_def_epa",
    "pass_epa",
    "rush_epa",
    "pressure_for",
    "pressure_allowed",
    "success_rate",
    "explosive_rate",
    "qb_adjustment",
    "prior_efficiency",
    "travel_miles",
    "timezone_crossings",
    "short_week",
    "bye_week",
)
MARGIN_FEATURE_NAMES = tuple(f"{key}_home_minus_away" for key in MARGIN_DIFF_KEYS)
TOTAL_FEATURE_NAMES = (
    *tuple(f"{key}_home_plus_away" for key in TOTAL_SUM_KEYS),
    "abs_rest_diff_days",
    "wind_mph_mean",
    "roof_closed_mean",
    "prior_weight_mean",
)


class NFLSymmetricLocationError(ValueError):
    pass


def _feature_pair(row: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    home = row.get("home_features")
    away = row.get("away_features")
    if not isinstance(home, Mapping) or not isinstance(away, Mapping):
        raise NFLSymmetricLocationError("NFL_LOCATION_G1_GAME_FEATURES_REQUIRED")
    _assert_market_blind(home, path="home_features")
    _assert_market_blind(away, path="away_features")
    if home.get("feature_contract") != NFL_M2_FEATURE_CONTRACT:
        raise NFLSymmetricLocationError("NFL_LOCATION_G1_HOME_FEATURE_CONTRACT_REQUIRED")
    if away.get("feature_contract") != NFL_M2_FEATURE_CONTRACT:
        raise NFLSymmetricLocationError("NFL_LOCATION_G1_AWAY_FEATURE_CONTRACT_REQUIRED")
    return home, away


def _num(features: Mapping[str, Any], key: str, side: str) -> float:
    if key not in features:
        raise NFLSymmetricLocationError(f"NFL_LOCATION_G1_FEATURE_MISSING:{side}:{key}")
    try:
        value = float(features[key])
    except (TypeError, ValueError) as exc:
        raise NFLSymmetricLocationError(
            f"NFL_LOCATION_G1_FEATURE_NUMERIC_REQUIRED:{side}:{key}"
        ) from exc
    if not isfinite(value):
        raise NFLSymmetricLocationError(f"NFL_LOCATION_G1_FEATURE_NONFINITE:{side}:{key}")
    return value


def margin_feature_vector(row: Mapping[str, Any]) -> np.ndarray:
    """Return the preregistered odd-symmetric non-intercept margin vector."""
    home, away = _feature_pair(row)
    values = [
        _num(home, key, "home") - _num(away, key, "away")
        for key in MARGIN_DIFF_KEYS
    ]
    return np.asarray(values, dtype=float)


def total_feature_vector(row: Mapping[str, Any]) -> np.ndarray:
    """Return the preregistered swap-invariant total vector."""
    home, away = _feature_pair(row)
    values = [
        _num(home, key, "home") + _num(away, key, "away")
        for key in TOTAL_SUM_KEYS
    ]
    rest_delta = 0.5 * (
        _num(home, "rest_diff_days", "home")
        - _num(away, "rest_diff_days", "away")
    )
    values.extend([
        abs(rest_delta),
        0.5 * (_num(home, "wind_mph", "home") + _num(away, "wind_mph", "away")),
        0.5 * (_num(home, "roof_closed", "home") + _num(away, "roof_closed", "away")),
        0.5 * (_num(home, "prior_weight", "home") + _num(away, "prior_weight", "away")),
    ])
    return np.asarray(values, dtype=float)


def _target(row: Mapping[str, Any], target: str) -> float:
    try:
        home = float(row["home_score"])
        away = float(row["away_score"])
    except (KeyError, TypeError, ValueError) as exc:
        raise NFLSymmetricLocationError("NFL_LOCATION_G1_REALIZED_SCORE_REQUIRED") from exc
    if not isfinite(home) or not isfinite(away):
        raise NFLSymmetricLocationError("NFL_LOCATION_G1_REALIZED_SCORE_NONFINITE")
    if target == "margin":
        return home - away
    if target == "total":
        return home + away
    raise NFLSymmetricLocationError(f"NFL_LOCATION_G1_TARGET_UNSUPPORTED:{target}")


@dataclass(frozen=True)
class _ComponentFit:
    means: tuple[float, ...]
    scales: tuple[float, ...]
    coefficients: tuple[float, ...]
    alpha: float

    @property
    def intercept(self) -> float:
        return float(self.coefficients[0])


def _fit_component(
    rows: Sequence[Mapping[str, Any]],
    *,
    target: str,
    alpha: float,
) -> _ComponentFit:
    data = [dict(row) for row in rows]
    if len(data) < 2:
        raise NFLSymmetricLocationError("NFL_LOCATION_G1_TRAINING_ROWS_INSUFFICIENT")
    penalty = float(alpha)
    if not isfinite(penalty) or penalty < 0.0:
        raise NFLSymmetricLocationError("NFL_LOCATION_G1_RIDGE_ALPHA_INVALID")
    vector = margin_feature_vector if target == "margin" else total_feature_vector
    raw_x = np.asarray([vector(row) for row in data], dtype=float)
    means = raw_x.mean(axis=0)
    scales = raw_x.std(axis=0)
    scales = np.where(scales > 1e-12, scales, 1.0)
    design = np.column_stack((np.ones(len(data), dtype=float), (raw_x - means) / scales))
    y = np.asarray([_target(row, target) for row in data], dtype=float)
    coefficients = _ridge_coefficients(design, y, penalty)
    return _ComponentFit(
        means=tuple(float(value) for value in means.tolist()),
        scales=tuple(float(value) for value in scales.tolist()),
        coefficients=tuple(float(value) for value in coefficients.tolist()),
        alpha=penalty,
    )


def _predict_component(
    fit: _ComponentFit,
    row: Mapping[str, Any],
    *,
    target: str,
) -> float:
    raw = margin_feature_vector(row) if target == "margin" else total_feature_vector(row)
    means = np.asarray(fit.means, dtype=float)
    scales = np.asarray(fit.scales, dtype=float)
    if raw.shape != means.shape or raw.shape != scales.shape:
        raise NFLSymmetricLocationError("NFL_LOCATION_G1_FEATURE_DIMENSION_MISMATCH")
    design = np.concatenate(([1.0], (raw - means) / scales))
    value = float(design @ np.asarray(fit.coefficients, dtype=float))
    if not isfinite(value):
        raise NFLSymmetricLocationError("NFL_LOCATION_G1_PREDICTION_NONFINITE")
    return value


def select_training_only_alpha(
    rows: Iterable[Mapping[str, Any]],
    *,
    target: str,
    alpha_grid: Sequence[float] = DEFAULT_ALPHA_GRID,
    min_train_seasons: int = 2,
) -> dict[str, Any]:
    """Select one ridge penalty using only expanding folds inside supplied rows."""
    data = [dict(row) for row in rows]
    if target not in {"margin", "total"}:
        raise NFLSymmetricLocationError(f"NFL_LOCATION_G1_TARGET_UNSUPPORTED:{target}")
    alphas = tuple(float(value) for value in alpha_grid)
    if not alphas or any(not isfinite(value) or value < 0.0 for value in alphas):
        raise NFLSymmetricLocationError("NFL_LOCATION_G1_ALPHA_GRID_INVALID")
    folds = season_walk_forward(
        data,
        season_key="season",
        min_train_seasons=int(min_train_seasons),
    )
    if not folds:
        raise NFLSymmetricLocationError("NFL_LOCATION_G1_INNER_FOLDS_REQUIRED")

    results: list[dict[str, Any]] = []
    for alpha in alphas:
        squared = 0.0
        absolute = 0.0
        n = 0
        fold_rows: list[dict[str, Any]] = []
        for fold in folds:
            fit = _fit_component(fold.train_rows, target=target, alpha=alpha)
            errors = []
            for raw in fold.test_rows:
                pred = _predict_component(fit, raw, target=target)
                err = pred - _target(raw, target)
                squared += err * err
                absolute += abs(err)
                n += 1
                errors.append(err)
            if errors:
                fold_rows.append({
                    "test_season": int(fold.test_season),
                    "train_seasons": [int(s) for s in fold.train_seasons],
                    "n": len(errors),
                    "rmse": sqrt(sum(err * err for err in errors) / len(errors)),
                    "mae": sum(abs(err) for err in errors) / len(errors),
                })
        if n <= 0:
            raise NFLSymmetricLocationError("NFL_LOCATION_G1_INNER_SCORING_EMPTY")
        results.append({
            "alpha": alpha,
            "n": n,
            "rmse": sqrt(squared / n),
            "mae": absolute / n,
            "folds": fold_rows,
        })

    # Frozen tie rule prefers stronger regularization when RMSE is identical.
    selected = min(results, key=lambda row: (float(row["rmse"]), -float(row["alpha"])))
    return {
        "target": target,
        "selected_alpha": float(selected["alpha"]),
        "selection_metric": "RMSE",
        "tie_break": "STRONGER_REGULARIZATION",
        "candidates": results,
    }


@dataclass(frozen=True)
class NFLSymmetricLocationG1:
    model_id: str
    candidate_family: str
    feature_contract: str
    margin_feature_names: tuple[str, ...]
    total_feature_names: tuple[str, ...]
    margin_feature_means: tuple[float, ...]
    margin_feature_scales: tuple[float, ...]
    margin_coefficients: tuple[float, ...]
    total_feature_means: tuple[float, ...]
    total_feature_scales: tuple[float, ...]
    total_coefficients: tuple[float, ...]
    margin_alpha: float
    total_alpha: float
    train_seasons: tuple[int, ...]

    @property
    def margin_intercept(self) -> float:
        return float(self.margin_coefficients[0])

    @property
    def total_intercept(self) -> float:
        return float(self.total_coefficients[0])

    def predict(self, row: Mapping[str, Any]) -> tuple[float, float]:
        margin_fit = _ComponentFit(
            self.margin_feature_means,
            self.margin_feature_scales,
            self.margin_coefficients,
            self.margin_alpha,
        )
        total_fit = _ComponentFit(
            self.total_feature_means,
            self.total_feature_scales,
            self.total_coefficients,
            self.total_alpha,
        )
        return (
            _predict_component(margin_fit, row, target="margin"),
            _predict_component(total_fit, row, target="total"),
        )


def fit_nfl_location_symmetric_g1(
    rows: Iterable[Mapping[str, Any]],
    *,
    margin_alpha: float,
    total_alpha: float,
) -> NFLSymmetricLocationG1:
    data = [dict(row) for row in rows]
    if len(data) < 2:
        raise NFLSymmetricLocationError("NFL_LOCATION_G1_TRAINING_ROWS_INSUFFICIENT")
    margin_fit = _fit_component(data, target="margin", alpha=float(margin_alpha))
    total_fit = _fit_component(data, target="total", alpha=float(total_alpha))
    seasons = tuple(sorted({int(row["season"]) for row in data}))
    return NFLSymmetricLocationG1(
        model_id=MODEL_ID,
        candidate_family=CANDIDATE_FAMILY,
        feature_contract=NFL_M2_FEATURE_CONTRACT,
        margin_feature_names=MARGIN_FEATURE_NAMES,
        total_feature_names=TOTAL_FEATURE_NAMES,
        margin_feature_means=margin_fit.means,
        margin_feature_scales=margin_fit.scales,
        margin_coefficients=margin_fit.coefficients,
        total_feature_means=total_fit.means,
        total_feature_scales=total_fit.scales,
        total_coefficients=total_fit.coefficients,
        margin_alpha=float(margin_alpha),
        total_alpha=float(total_alpha),
        train_seasons=seasons,
    )


def team_means_from_location(margin_mu: float, total_mu: float) -> dict[str, float]:
    margin = float(margin_mu)
    total = float(total_mu)
    if not isfinite(margin) or not isfinite(total):
        raise NFLSymmetricLocationError("NFL_LOCATION_G1_MEAN_NONFINITE")
    home = 0.5 * (total + margin)
    away = 0.5 * (total - margin)
    if home <= 0.0 or away <= 0.0:
        raise NFLSymmetricLocationError("NFL_LOCATION_G1_TEAM_MEAN_NONPOSITIVE")
    return {"mean_home": home, "mean_away": away}


def discrete_v2_grid_from_location(
    margin_mu: float,
    total_mu: float,
) -> list[list[float]]:
    """Handoff only; the frozen discrete_v2 shape bytes are not modified."""
    means = team_means_from_location(margin_mu, total_mu)
    return score_grid(means["mean_home"], means["mean_away"])


__all__ = [
    "CANDIDATE_FAMILY",
    "DEFAULT_ALPHA_GRID",
    "MARGIN_DIFF_KEYS",
    "MARGIN_FEATURE_NAMES",
    "MODEL_ID",
    "NFLSymmetricLocationError",
    "NFLSymmetricLocationG1",
    "TOTAL_FEATURE_NAMES",
    "TOTAL_SUM_KEYS",
    "discrete_v2_grid_from_location",
    "fit_nfl_location_symmetric_g1",
    "margin_feature_vector",
    "select_training_only_alpha",
    "team_means_from_location",
    "total_feature_vector",
]
