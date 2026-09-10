"""Temporal-only ridge selection and coefficient diagnostics for CFB model fitting.

This module is training policy only. It never reads sportsbook data and it never
changes promotion state. Candidate alphas are selected using season-ordered
validation folds: each validation season is predicted only by models fit on prior
seasons. The final model is then fit on the complete declared training bundle.
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from .joint_model import CFBJointScoreModel, fit_cfb_joint_score_model

CFB_RIDGE_POLICY_VERSION = "CFB_TEMPORAL_RIDGE_CV_V1"
CFB_FIXED_RIDGE_POLICY_VERSION = "CFB_FIXED_RIDGE_ALPHA_V1"
CFB_RIDGE_ALPHA_GRID = (0.1, 1.0, 10.0, 100.0, 300.0, 1000.0)
CFB_MIN_TEMPORAL_FOLDS = 2
CFB_MIN_FOLD_TRAIN_ROWS = 20
CFB_MIN_FOLD_VALIDATION_ROWS = 5


class CFBFitPolicyError(ValueError):
    pass


def _season(row: Mapping[str, Any]) -> int:
    try:
        return int(row["season"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CFBFitPolicyError("CFB_RIDGE_CV_SEASON_INVALID") from exc


def _sort_key(row: Mapping[str, Any]) -> tuple[int, int, str]:
    try:
        week = int(row.get("week", 0))
    except (TypeError, ValueError) as exc:
        raise CFBFitPolicyError("CFB_RIDGE_CV_WEEK_INVALID") from exc
    return _season(row), week, str(row.get("game_id") or "")


def _candidate_grid(values: Sequence[float]) -> tuple[float, ...]:
    out: list[float] = []
    for raw in values:
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise CFBFitPolicyError("CFB_RIDGE_ALPHA_GRID_INVALID") from exc
        if not isfinite(value) or value < 0:
            raise CFBFitPolicyError("CFB_RIDGE_ALPHA_GRID_INVALID")
        if value not in out:
            out.append(value)
    if len(out) < 2:
        raise CFBFitPolicyError("CFB_RIDGE_ALPHA_GRID_INSUFFICIENT")
    return tuple(sorted(out))


def _combined_mse(model: CFBJointScoreModel, rows: Sequence[Mapping[str, Any]]) -> tuple[float, float, float]:
    home_err: list[float] = []
    away_err: list[float] = []
    for row in rows:
        home_pred, away_pred = model.predict_means(row)
        try:
            home_actual = float(row["home_score"])
            away_actual = float(row["away_score"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CFBFitPolicyError("CFB_RIDGE_CV_SCORE_INVALID") from exc
        if not all(isfinite(x) for x in (home_actual, away_actual)):
            raise CFBFitPolicyError("CFB_RIDGE_CV_SCORE_INVALID")
        home_err.append((home_pred - home_actual) ** 2)
        away_err.append((away_pred - away_actual) ** 2)
    if not home_err:
        raise CFBFitPolicyError("CFB_RIDGE_CV_VALIDATION_EMPTY")
    home_mse = float(np.mean(np.asarray(home_err, dtype=float)))
    away_mse = float(np.mean(np.asarray(away_err, dtype=float)))
    return home_mse, away_mse, float((home_mse + away_mse) / 2.0)


def _sign(value: float, *, eps: float = 1e-9) -> int:
    if value > eps:
        return 1
    if value < -eps:
        return -1
    return 0


def _coefficient_stability(
    models: Sequence[CFBJointScoreModel],
    final_model: CFBJointScoreModel,
) -> dict[str, dict[str, dict[str, Any]]]:
    if not models:
        return {"home": {}, "away": {}}
    names = tuple(final_model.feature_names)
    output: dict[str, dict[str, dict[str, Any]]] = {"home": {}, "away": {}}
    for target, attr in (("home", "home_coefficients"), ("away", "away_coefficients")):
        final = tuple(float(x) for x in getattr(final_model, attr))[1:]
        for index, name in enumerate(names):
            values = [float(getattr(model, attr)[index + 1]) for model in models]
            signs = [_sign(value) for value in values]
            pos = sum(value > 0 for value in signs)
            neg = sum(value < 0 for value in signs)
            zero = sum(value == 0 for value in signs)
            nonzero = pos + neg
            dominant = max(pos, neg) / nonzero if nonzero else 0.0
            output[target][name] = {
                "final_coefficient": float(final[index]),
                "fold_coefficients": values,
                "positive_folds": pos,
                "negative_folds": neg,
                "zero_folds": zero,
                "dominant_sign_share": float(dominant),
                "sign_flip_observed": bool(pos and neg),
            }
    return output


def fit_cfb_with_temporal_ridge_selection(
    rows: Iterable[Mapping[str, Any]],
    *,
    alpha_grid: Sequence[float] = CFB_RIDGE_ALPHA_GRID,
) -> tuple[CFBJointScoreModel, dict[str, Any]]:
    """Select ridge alpha on prior-season-only folds and fit the final model."""
    data = sorted((dict(row) for row in rows), key=_sort_key)
    if len(data) < CFB_MIN_FOLD_TRAIN_ROWS + CFB_MIN_FOLD_VALIDATION_ROWS:
        raise CFBFitPolicyError("CFB_RIDGE_CV_ROWS_INSUFFICIENT")
    seasons = sorted({_season(row) for row in data})
    if len(seasons) < 3:
        raise CFBFitPolicyError("CFB_RIDGE_CV_REQUIRES_THREE_SEASONS")
    grid = _candidate_grid(alpha_grid)

    folds: list[dict[str, Any]] = []
    for validation_season in seasons[1:]:
        train = [row for row in data if _season(row) < validation_season]
        validation = [row for row in data if _season(row) == validation_season]
        if len(train) < CFB_MIN_FOLD_TRAIN_ROWS or len(validation) < CFB_MIN_FOLD_VALIDATION_ROWS:
            continue
        folds.append({
            "validation_season": validation_season,
            "train_seasons": sorted({_season(row) for row in train}),
            "train_rows": train,
            "validation_rows": validation,
        })
    if len(folds) < CFB_MIN_TEMPORAL_FOLDS:
        raise CFBFitPolicyError("CFB_RIDGE_CV_FOLDS_INSUFFICIENT")

    score_by_alpha: dict[float, list[dict[str, Any]]] = {alpha: [] for alpha in grid}
    for alpha in grid:
        for fold in folds:
            model = fit_cfb_joint_score_model(fold["train_rows"], ridge_alpha=alpha)
            home_mse, away_mse, combined_mse = _combined_mse(model, fold["validation_rows"])
            score_by_alpha[alpha].append({
                "validation_season": int(fold["validation_season"]),
                "train_seasons": list(fold["train_seasons"]),
                "train_row_count": len(fold["train_rows"]),
                "validation_row_count": len(fold["validation_rows"]),
                "home_mse": home_mse,
                "away_mse": away_mse,
                "combined_mse": combined_mse,
            })

    mean_mse = {
        alpha: float(np.mean([row["combined_mse"] for row in scores]))
        for alpha, scores in score_by_alpha.items()
    }
    selected = min(grid, key=lambda alpha: (mean_mse[alpha], alpha))
    selected_fold_models = [
        fit_cfb_joint_score_model(fold["train_rows"], ridge_alpha=selected)
        for fold in folds
    ]
    final_model = fit_cfb_joint_score_model(data, ridge_alpha=selected)
    diagnostics = {
        "policy_version": CFB_RIDGE_POLICY_VERSION,
        "candidate_alphas": list(grid),
        "selected_alpha": float(selected),
        "selection_metric": "EQUAL_FOLD_MEAN_OF_HOME_AWAY_MSE",
        "tie_break": "LOWEST_ALPHA",
        "season_order": seasons,
        "fold_count": len(folds),
        "candidate_mean_combined_mse": {str(alpha): mean_mse[alpha] for alpha in grid},
        "selected_alpha_folds": score_by_alpha[selected],
        "coefficient_sign_stability": _coefficient_stability(selected_fold_models, final_model),
    }
    return final_model, diagnostics
