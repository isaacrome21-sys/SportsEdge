"""Training-only selector for NFL M2 V2C independent ridge penalties.

For each outer training set, use only inner walk-forward seasons to choose margin
and total ridge penalties independently. The objective is realized-score MSE for
the corresponding conditional mean. Sportsbook fields are never read.
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Iterable

from sportsedge.core.walkforward.season import season_walk_forward
from .m2_v2c_candidate import fit_nfl_m2_v2c_candidate

NFL_M2_V2C_SELECTOR_CONTRACT = "NFL_M2_V2C_NESTED_SPLIT_ALPHA_SELECTOR_V1"
DEFAULT_ALPHA_GRID = (0.0, 1.0, 3.0, 10.0, 30.0, 100.0)


def _alpha_grid(values: Iterable[float]) -> tuple[float, ...]:
    out = []
    for value in values:
        number = float(value)
        if not isfinite(number) or number < 0.0:
            raise ValueError("NFL_M2_V2C_SELECTOR_ALPHA_INVALID")
        out.append(number)
    grid = tuple(sorted(set(out)))
    if not grid:
        raise ValueError("NFL_M2_V2C_SELECTOR_GRID_EMPTY")
    return grid


def select_nfl_m2_v2c_alphas(
    rows: Iterable[dict[str, Any]],
    *,
    alpha_grid: Iterable[float] = DEFAULT_ALPHA_GRID,
    min_inner_train_seasons: int = 2,
    fallback_alpha: float = 10.0,
) -> dict[str, Any]:
    data = [dict(row) for row in rows]
    grid = _alpha_grid(alpha_grid)
    fallback = float(fallback_alpha)
    if not isfinite(fallback) or fallback < 0.0:
        raise ValueError("NFL_M2_V2C_SELECTOR_FALLBACK_INVALID")
    minimum = int(min_inner_train_seasons)
    if minimum < 1:
        raise ValueError("NFL_M2_V2C_SELECTOR_MIN_INNER_TRAIN_SEASONS_INVALID")
    outer_training_seasons = tuple(sorted({int(row["season"]) for row in data}))
    if not outer_training_seasons:
        raise ValueError("NFL_M2_V2C_SELECTOR_TRAINING_SEASONS_REQUIRED")

    folds = season_walk_forward(data, season_key="season", min_train_seasons=minimum)
    if not folds:
        return {
            "contract": NFL_M2_V2C_SELECTOR_CONTRACT,
            "status": "INSUFFICIENT_INNER_FOLDS_FALLBACK",
            "market_data_used": False,
            "outer_training_seasons": list(outer_training_seasons),
            "inner_test_seasons": [],
            "alpha_grid": list(grid),
            "evaluation_game_count": 0,
            "selected_margin_ridge_alpha": fallback,
            "selected_total_ridge_alpha": fallback,
            "margin_scores": [],
            "total_scores": [],
        }

    margin_totals = {alpha: [0.0, 0] for alpha in grid}
    total_totals = {alpha: [0.0, 0] for alpha in grid}
    inner_test_seasons: list[int] = []

    for fold in folds:
        test_season = int(fold.test_season)
        inner_test_seasons.append(test_season)
        for alpha in grid:
            margin_model = fit_nfl_m2_v2c_candidate(
                fold.train_rows,
                margin_ridge_alpha=alpha,
                total_ridge_alpha=fallback,
            )
            total_model = fit_nfl_m2_v2c_candidate(
                fold.train_rows,
                margin_ridge_alpha=fallback,
                total_ridge_alpha=alpha,
            )
            if test_season in margin_model.train_seasons or test_season in total_model.train_seasons:
                raise ValueError("NFL_M2_V2C_SELECTOR_TEST_SEASON_IN_TRAINING")
            for raw in fold.test_rows:
                row = dict(raw)
                home = float(row["home_score"])
                away = float(row["away_score"])
                observed_margin = home - away
                observed_total = home + away
                margin_pred, _ = margin_model.predict(row)
                _, total_pred = total_model.predict(row)
                margin_totals[alpha][0] += (margin_pred - observed_margin) ** 2
                margin_totals[alpha][1] += 1
                total_totals[alpha][0] += (total_pred - observed_total) ** 2
                total_totals[alpha][1] += 1

    def score_rows(accumulator: dict[float, list[float | int]]) -> list[dict[str, float | int]]:
        result = []
        for alpha in grid:
            squared_error, count_value = accumulator[alpha]
            count = int(count_value)
            if count <= 0:
                raise ValueError("NFL_M2_V2C_SELECTOR_NO_INNER_EVALUATIONS")
            result.append({
                "ridge_alpha": alpha,
                "evaluation_game_count": count,
                "mean_squared_error": float(squared_error) / count,
            })
        return result

    margin_scores = score_rows(margin_totals)
    total_scores = score_rows(total_totals)
    margin_winner = min(margin_scores, key=lambda row: (float(row["mean_squared_error"]), abs(float(row["ridge_alpha"]) - fallback), float(row["ridge_alpha"])))
    total_winner = min(total_scores, key=lambda row: (float(row["mean_squared_error"]), abs(float(row["ridge_alpha"]) - fallback), float(row["ridge_alpha"])))
    return {
        "contract": NFL_M2_V2C_SELECTOR_CONTRACT,
        "status": "SELECTED_FROM_INNER_WALK_FORWARD",
        "market_data_used": False,
        "outer_training_seasons": list(outer_training_seasons),
        "inner_test_seasons": sorted(set(inner_test_seasons)),
        "alpha_grid": list(grid),
        "evaluation_game_count": int(margin_scores[0]["evaluation_game_count"]),
        "selected_margin_ridge_alpha": float(margin_winner["ridge_alpha"]),
        "selected_total_ridge_alpha": float(total_winner["ridge_alpha"]),
        "margin_scores": margin_scores,
        "total_scores": total_scores,
        "tie_break": "MSE_THEN_DISTANCE_TO_FALLBACK_THEN_ALPHA",
    }
