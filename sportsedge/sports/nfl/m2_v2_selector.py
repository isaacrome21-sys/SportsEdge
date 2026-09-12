"""Nested training-only selector for NFL M2 V2 empirical-support bandwidths.

This module is diagnostic-only. It never consumes sportsbook lines or prices.
For each outer training set, it performs an inner season walk-forward and chooses
margin/total kernel scales from a frozen grid using realized-score CRPS only.
The untouched outer test season must never be passed to this selector.
"""
from __future__ import annotations

from dataclasses import replace
from math import isfinite
from typing import Any, Iterable

from sportsedge.core.walkforward.season import season_walk_forward
from .m2_v2_candidate import (
    derive_nfl_m2_v2_score_distribution,
    fit_nfl_m2_v2_candidate,
)

NFL_M2_V2_SELECTOR_CONTRACT = "NFL_M2_V2_NESTED_TRAINING_KERNEL_SELECTOR_V1"
DEFAULT_KERNEL_SCALE_GRID = (0.50, 0.75, 1.00, 1.25, 1.50, 2.00)


def _positive_scale(value: Any, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"NFL_M2_V2_SELECTOR_{field}_INVALID") from exc
    if not isfinite(out) or out <= 0.0:
        raise ValueError(f"NFL_M2_V2_SELECTOR_{field}_INVALID")
    return out


def _scale_grid(values: Iterable[float]) -> tuple[float, ...]:
    grid = tuple(sorted({_positive_scale(value, "GRID_SCALE") for value in values}))
    if not grid:
        raise ValueError("NFL_M2_V2_SELECTOR_GRID_EMPTY")
    return grid


def _integer_score(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"NFL_M2_V2_SELECTOR_{field}_INTEGER_REQUIRED")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"NFL_M2_V2_SELECTOR_{field}_INTEGER_REQUIRED") from exc
    if not isfinite(number) or number < 0.0 or abs(number - round(number)) > 1e-12:
        raise ValueError(f"NFL_M2_V2_SELECTOR_{field}_INTEGER_REQUIRED")
    return int(round(number))


def _weighted_crps(
    distribution: Iterable[dict[str, float | int]],
    *,
    field: str,
    observed: int,
) -> float:
    """Exact weighted empirical CRPS in O(n log n)."""
    points: list[tuple[float, float]] = []
    weight_sum = 0.0
    for row in distribution:
        value = float(row[field])
        weight = float(row["weight"])
        if not isfinite(value) or not isfinite(weight) or weight < 0.0:
            raise ValueError("NFL_M2_V2_SELECTOR_DISTRIBUTION_INVALID")
        points.append((value, weight))
        weight_sum += weight
    if not points or abs(weight_sum - 1.0) > 1e-8:
        raise ValueError("NFL_M2_V2_SELECTOR_DISTRIBUTION_NOT_NORMALIZED")

    first = sum(weight * abs(value - observed) for value, weight in points)
    cumulative_weight = 0.0
    cumulative_weighted_value = 0.0
    half_pair_expectation = 0.0
    for value, weight in sorted(points):
        half_pair_expectation += weight * (
            value * cumulative_weight - cumulative_weighted_value
        )
        cumulative_weight += weight
        cumulative_weighted_value += weight * value
    score = first - half_pair_expectation
    if not isfinite(score) or score < -1e-10:
        raise ValueError("NFL_M2_V2_SELECTOR_CRPS_INVALID")
    return max(0.0, float(score))


def select_nfl_m2_v2_kernel_scales(
    rows: Iterable[dict[str, Any]],
    *,
    ridge_alpha: float = 10.0,
    scale_grid: Iterable[float] = DEFAULT_KERNEL_SCALE_GRID,
    min_inner_train_seasons: int = 2,
    fallback_scale: float = 1.0,
) -> dict[str, Any]:
    """Choose split kernel scales using inner walk-forward training evidence only.

    The objective is the mean of margin CRPS plus total CRPS on inner held-out
    seasons. CRPS uses only realized scores and the market-blind score distribution.
    Sportsbook lines/prices are intentionally never read here.
    """
    data = [dict(row) for row in rows]
    grid = _scale_grid(scale_grid)
    fallback = _positive_scale(fallback_scale, "FALLBACK_SCALE")
    minimum = int(min_inner_train_seasons)
    if minimum < 1:
        raise ValueError("NFL_M2_V2_SELECTOR_MIN_INNER_TRAIN_SEASONS_INVALID")
    train_seasons = tuple(sorted({int(row["season"]) for row in data}))
    if not train_seasons:
        raise ValueError("NFL_M2_V2_SELECTOR_TRAINING_SEASONS_REQUIRED")

    folds = season_walk_forward(
        data,
        season_key="season",
        min_train_seasons=minimum,
    )
    if not folds:
        return {
            "contract": NFL_M2_V2_SELECTOR_CONTRACT,
            "status": "INSUFFICIENT_INNER_FOLDS_FALLBACK",
            "market_data_used": False,
            "outer_training_seasons": list(train_seasons),
            "inner_test_seasons": [],
            "scale_grid": list(grid),
            "evaluation_game_count": 0,
            "selected_margin_kernel_scale": fallback,
            "selected_total_kernel_scale": fallback,
            "selection_objective": None,
            "candidate_scores": [],
            "tie_break": "OBJECTIVE_THEN_DISTANCE_TO_1_THEN_MARGIN_THEN_TOTAL",
        }

    totals: dict[tuple[float, float], list[float]] = {
        (margin_scale, total_scale): [0.0, 0.0, 0.0]
        for margin_scale in grid
        for total_scale in grid
    }
    inner_test_seasons: list[int] = []
    evaluation_game_count = 0

    for fold in folds:
        base_model = fit_nfl_m2_v2_candidate(
            fold.train_rows,
            ridge_alpha=ridge_alpha,
            kernel_scale=fallback,
            margin_kernel_scale=fallback,
            total_kernel_scale=fallback,
        )
        test_season = int(fold.test_season)
        if test_season in base_model.train_seasons:
            raise ValueError("NFL_M2_V2_SELECTOR_TEST_SEASON_IN_TRAINING")
        inner_test_seasons.append(test_season)

        for raw in fold.test_rows:
            row = dict(raw)
            home_score = _integer_score(row.get("home_score"), "HOME_SCORE")
            away_score = _integer_score(row.get("away_score"), "AWAY_SCORE")
            observed_margin = home_score - away_score
            observed_total = home_score + away_score
            evaluation_game_count += 1

            for margin_scale in grid:
                for total_scale in grid:
                    model = replace(
                        base_model,
                        margin_kernel_scale=margin_scale,
                        total_kernel_scale=total_scale,
                    )
                    distribution = derive_nfl_m2_v2_score_distribution(model, row)
                    margin_crps = _weighted_crps(
                        distribution,
                        field="margin",
                        observed=observed_margin,
                    )
                    total_crps = _weighted_crps(
                        distribution,
                        field="total",
                        observed=observed_total,
                    )
                    accumulator = totals[(margin_scale, total_scale)]
                    accumulator[0] += margin_crps
                    accumulator[1] += total_crps
                    accumulator[2] += 1.0

    if evaluation_game_count <= 0:
        raise ValueError("NFL_M2_V2_SELECTOR_NO_INNER_EVALUATIONS")

    candidate_scores: list[dict[str, float | int]] = []
    for (margin_scale, total_scale), (margin_sum, total_sum, count_float) in sorted(totals.items()):
        count = int(count_float)
        if count != evaluation_game_count:
            raise ValueError("NFL_M2_V2_SELECTOR_EVALUATION_COUNT_MISMATCH")
        mean_margin = margin_sum / count
        mean_total = total_sum / count
        candidate_scores.append({
            "margin_kernel_scale": margin_scale,
            "total_kernel_scale": total_scale,
            "evaluation_game_count": count,
            "mean_margin_crps": mean_margin,
            "mean_total_crps": mean_total,
            "objective": mean_margin + mean_total,
        })

    winner = min(
        candidate_scores,
        key=lambda row: (
            float(row["objective"]),
            abs(float(row["margin_kernel_scale"]) - 1.0)
            + abs(float(row["total_kernel_scale"]) - 1.0),
            float(row["margin_kernel_scale"]),
            float(row["total_kernel_scale"]),
        ),
    )
    return {
        "contract": NFL_M2_V2_SELECTOR_CONTRACT,
        "status": "SELECTED_FROM_INNER_WALK_FORWARD",
        "market_data_used": False,
        "outer_training_seasons": list(train_seasons),
        "inner_test_seasons": sorted(set(inner_test_seasons)),
        "scale_grid": list(grid),
        "evaluation_game_count": evaluation_game_count,
        "selected_margin_kernel_scale": float(winner["margin_kernel_scale"]),
        "selected_total_kernel_scale": float(winner["total_kernel_scale"]),
        "selection_objective": float(winner["objective"]),
        "candidate_scores": candidate_scores,
        "tie_break": "OBJECTIVE_THEN_DISTANCE_TO_1_THEN_MARGIN_THEN_TOTAL",
    }
