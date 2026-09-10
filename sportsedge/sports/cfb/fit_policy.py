"""Deterministic, season-ordered ridge selection for the CFB joint score model.

This module is an engineering fit policy, not promotion evidence.  It never
reads market data and never evaluates forward-season betting performance.
"""
from __future__ import annotations

from math import sqrt
from statistics import fmean, median, pstdev
from typing import Any, Iterable, Mapping, Sequence

from .joint_model import CFBJointScoreModel, fit_cfb_joint_score_model

CFB_TEMPORAL_FIT_POLICY_VERSION = "CFB_TEMPORAL_RIDGE_SELECTION_V1"
DEFAULT_CFB_RIDGE_ALPHA_GRID = (0.1, 1.0, 3.0, 10.0, 30.0, 100.0, 300.0)
CFB_TEMPORAL_SELECTION_METRIC = "JOINT_HOME_AWAY_SCORE_RMSE"
CFB_TEMPORAL_TIE_BREAK = "LOWEST_MEAN_RMSE_THEN_LOWEST_ALPHA"


class CFBFitPolicyError(ValueError):
    pass


def _season(row: Mapping[str, Any]) -> int:
    try:
        return int(row["season"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CFBFitPolicyError("CFB_TEMPORAL_FIT_SEASON_INVALID") from exc


def _joint_rmse(model: CFBJointScoreModel, rows: Sequence[Mapping[str, Any]]) -> float:
    if not rows:
        raise CFBFitPolicyError("CFB_TEMPORAL_FIT_VALIDATION_ROWS_EMPTY")
    squared = 0.0
    for row in rows:
        home_pred, away_pred = model.predict_means(row)
        try:
            home = float(row["home_score"])
            away = float(row["away_score"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CFBFitPolicyError("CFB_TEMPORAL_FIT_SCORE_INVALID") from exc
        squared += (home_pred - home) ** 2 + (away_pred - away) ** 2
    return sqrt(squared / (2.0 * len(rows)))


def _sign_stability(values: Sequence[float], *, epsilon: float = 1e-12) -> float:
    if not values:
        return 0.0
    positive = sum(value > epsilon for value in values)
    negative = sum(value < -epsilon for value in values)
    zero = len(values) - positive - negative
    return max(positive, negative, zero) / len(values)


def _coefficient_stability(
    final_model: CFBJointScoreModel,
    fold_models: Sequence[CFBJointScoreModel],
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    for index, name in enumerate(final_model.feature_names, start=1):
        home_values = [float(model.home_coefficients[index]) for model in fold_models]
        away_values = [float(model.away_coefficients[index]) for model in fold_models]
        diagnostics.append({
            "feature": name,
            "home_final_coefficient": float(final_model.home_coefficients[index]),
            "away_final_coefficient": float(final_model.away_coefficients[index]),
            "home_fold_coefficients": home_values,
            "away_fold_coefficients": away_values,
            "home_sign_stability_rate": _sign_stability(home_values),
            "away_sign_stability_rate": _sign_stability(away_values),
            "home_mean_abs": fmean(abs(value) for value in home_values),
            "away_mean_abs": fmean(abs(value) for value in away_values),
            "home_median_abs": median(abs(value) for value in home_values),
            "away_median_abs": median(abs(value) for value in away_values),
            "home_min": min(home_values),
            "home_max": max(home_values),
            "away_min": min(away_values),
            "away_max": max(away_values),
            "home_std": pstdev(home_values),
            "away_std": pstdev(away_values),
        })
    return diagnostics


def fit_cfb_joint_score_model_temporal(
    rows: Iterable[Mapping[str, Any]],
    *,
    alpha_grid: Sequence[float] = DEFAULT_CFB_RIDGE_ALPHA_GRID,
) -> tuple[CFBJointScoreModel, dict[str, Any]]:
    """Select ridge alpha by expanding-season validation, then fit all rows.

    At least three distinct seasons are required.  Every validation fold trains
    only on strictly earlier seasons; no random K-fold or same-season leakage is
    allowed.  The result is deterministic for identical input rows and code.
    """
    data = [dict(row) for row in rows]
    seasons = sorted({_season(row) for row in data})
    if len(seasons) < 3:
        raise CFBFitPolicyError("CFB_TEMPORAL_FIT_SEASONS_INSUFFICIENT")

    try:
        grid = tuple(sorted({float(value) for value in alpha_grid}))
    except (TypeError, ValueError) as exc:
        raise CFBFitPolicyError("CFB_TEMPORAL_FIT_ALPHA_GRID_INVALID") from exc
    if not grid or any(value < 0 for value in grid):
        raise CFBFitPolicyError("CFB_TEMPORAL_FIT_ALPHA_GRID_INVALID")

    fold_specs: list[tuple[int, list[dict[str, Any]], list[dict[str, Any]], tuple[int, ...]]] = []
    for validation_season in seasons[2:]:
        train_seasons = tuple(season for season in seasons if season < validation_season)
        train_rows = [row for row in data if _season(row) in train_seasons]
        validation_rows = [row for row in data if _season(row) == validation_season]
        if len(train_rows) < 20:
            raise CFBFitPolicyError(f"CFB_TEMPORAL_FIT_TRAIN_ROWS_INSUFFICIENT:{validation_season}")
        if not validation_rows:
            raise CFBFitPolicyError(f"CFB_TEMPORAL_FIT_VALIDATION_ROWS_EMPTY:{validation_season}")
        fold_specs.append((validation_season, train_rows, validation_rows, train_seasons))

    candidate_rows: list[dict[str, Any]] = []
    scores_by_alpha: dict[float, tuple[float, ...]] = {}
    for alpha in grid:
        fold_scores: list[float] = []
        for _, train_rows, validation_rows, _ in fold_specs:
            model = fit_cfb_joint_score_model(train_rows, ridge_alpha=alpha)
            fold_scores.append(_joint_rmse(model, validation_rows))
        scores_by_alpha[alpha] = tuple(fold_scores)
        candidate_rows.append({
            "alpha": alpha,
            "fold_rmse": list(fold_scores),
            "mean_rmse": fmean(fold_scores),
        })

    selected = min(candidate_rows, key=lambda item: (item["mean_rmse"], item["alpha"]))
    selected_alpha = float(selected["alpha"])
    final_model = fit_cfb_joint_score_model(data, ridge_alpha=selected_alpha)

    selected_fold_models: list[CFBJointScoreModel] = []
    folds: list[dict[str, Any]] = []
    selected_scores = scores_by_alpha[selected_alpha]
    for index, (validation_season, train_rows, validation_rows, train_seasons) in enumerate(fold_specs):
        fold_model = fit_cfb_joint_score_model(train_rows, ridge_alpha=selected_alpha)
        selected_fold_models.append(fold_model)
        folds.append({
            "train_seasons": list(train_seasons),
            "validation_season": validation_season,
            "train_row_count": len(train_rows),
            "validation_row_count": len(validation_rows),
            "selected_alpha_rmse": selected_scores[index],
        })

    policy = {
        "policy_version": CFB_TEMPORAL_FIT_POLICY_VERSION,
        "mode": "TEMPORAL_EXPANDING_SEASON_SELECTION",
        "alpha_grid": list(grid),
        "selected_alpha": selected_alpha,
        "metric": CFB_TEMPORAL_SELECTION_METRIC,
        "tie_break": CFB_TEMPORAL_TIE_BREAK,
        "candidate_scores": candidate_rows,
        "folds": folds,
        "coefficient_stability": _coefficient_stability(final_model, selected_fold_models),
        "promotion_evidence": False,
    }
    return final_model, policy


__all__ = [
    "CFBFitPolicyError",
    "CFB_TEMPORAL_FIT_POLICY_VERSION",
    "DEFAULT_CFB_RIDGE_ALPHA_GRID",
    "fit_cfb_joint_score_model_temporal",
]
