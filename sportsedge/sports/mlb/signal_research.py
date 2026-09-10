"""Leakage-resistant MLB feature-family research on pre-2025 StatsAPI games.

This module is intentionally isolated from the production engine.  It compares a
small, predeclared set of score-model feature families using 2023 for family
selection and 2024 for a one-shot development confirmation.  The sacred 2025
holdout is never accepted by this research path, and no market prices, betting
splits, or promotion state are inputs.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date as Date
from itertools import groupby
from math import isfinite
from typing import Any, Mapping, Sequence

import numpy as np

MLB_SIGNAL_RESEARCH_VERSION = "MLB_SIGNAL_DEV_PRE2025_V1"
MLB_SIGNAL_ALLOWED_SEASONS = (2021, 2022, 2023, 2024)
MLB_SIGNAL_SELECTION_SEASON = 2023
MLB_SIGNAL_CONFIRMATION_SEASON = 2024
MLB_SIGNAL_SACRED_HOLDOUT_SEASON = 2025
MLB_SIGNAL_ALPHAS = (0.1, 0.3, 1.0, 3.0, 10.0, 30.0, 100.0, 300.0)
MLB_SIGNAL_MIN_PRIOR = 20
MLB_SIGNAL_LONG_WINDOW = 30
MLB_SIGNAL_SHORT_WINDOW = 10

BASE_CORE_FEATURES = (
    "home_rs_roll30",
    "home_ra_roll30",
    "away_rs_roll30",
    "away_ra_roll30",
    "home_net_roll30",
    "away_net_roll30",
    "home_rs_home_split30",
    "away_rs_away_split30",
)
FEATURE_FAMILIES: dict[str, tuple[str, ...]] = {
    # Exact conceptual baseline already used by fit_mlb_baseline.py.
    "baseline_v1": BASE_CORE_FEATURES + ("home_rest_proxy", "away_rest_proxy"),
    # Predeclared recency test: retain long window and add short-window offense,
    # defense, and net form for both clubs.
    "recency_multiwindow_v1": BASE_CORE_FEATURES
    + ("home_rest_proxy", "away_rest_proxy")
    + (
        "home_rs_roll10", "home_ra_roll10", "away_rs_roll10", "away_ra_roll10",
        "home_net_roll10", "away_net_roll10",
    ),
    # Predeclared venue-defense test: baseline plus runs allowed in the relevant
    # home/away venue split, which the prior baseline omitted.
    "venue_defense_v1": BASE_CORE_FEATURES
    + ("home_rest_proxy", "away_rest_proxy", "home_ra_home_split30", "away_ra_away_split30"),
    # Rest is represented compactly as the matchup differential instead of two
    # separate, highly collinear raw rest features.
    "rest_diff_compact_v1": BASE_CORE_FEATURES + ("rest_diff",),
    # One predeclared combined family.  No combinatorial feature search occurs.
    "combined_predeclared_v1": BASE_CORE_FEATURES
    + (
        "rest_diff",
        "home_rs_roll10", "home_ra_roll10", "away_rs_roll10", "away_ra_roll10",
        "home_net_roll10", "away_net_roll10",
        "home_ra_home_split30", "away_ra_away_split30",
    ),
}


class MLBSignalResearchError(ValueError):
    pass


def validate_research_seasons(seasons: Sequence[int]) -> tuple[int, ...]:
    try:
        values = tuple(sorted({int(value) for value in seasons}))
    except (TypeError, ValueError) as exc:
        raise MLBSignalResearchError("MLB_SIGNAL_DEV_SEASONS_INVALID") from exc
    if not values:
        raise MLBSignalResearchError("MLB_SIGNAL_DEV_SEASONS_EMPTY")
    if MLB_SIGNAL_SACRED_HOLDOUT_SEASON in values or any(value > MLB_SIGNAL_CONFIRMATION_SEASON for value in values):
        raise MLBSignalResearchError("MLB_SIGNAL_DEV_SACRED_2025_HOLDOUT_FORBIDDEN")
    if any(value not in MLB_SIGNAL_ALLOWED_SEASONS for value in values):
        raise MLBSignalResearchError("MLB_SIGNAL_DEV_SEASON_OUTSIDE_PREREGISTERED_WINDOW")
    required = set(MLB_SIGNAL_ALLOWED_SEASONS)
    if set(values) != required:
        raise MLBSignalResearchError("MLB_SIGNAL_DEV_REQUIRES_EXACT_2021_2024_WINDOW")
    return values


def _mean_tail(values: Sequence[float], n: int) -> float:
    if not values:
        return 0.0
    return float(np.mean(np.asarray(values[-n:], dtype=float)))


def _day_gap(last_played: Mapping[int, str], team: int, current_date: str) -> float:
    previous = last_played.get(team)
    if not previous:
        return 1.0
    try:
        a = Date.fromisoformat(previous)
        b = Date.fromisoformat(current_date)
    except ValueError as exc:
        raise MLBSignalResearchError("MLB_SIGNAL_DEV_DATE_INVALID") from exc
    gap = (b - a).days
    return float(min(max(gap, 0), 7))


def build_feature_rows(games: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Build all predeclared feature families from the same prior-date snapshot.

    Histories match the existing baseline convention and carry across seasons.
    All games on one calendar date are emitted before that date updates history,
    preventing same-day ordering leakage.
    """
    ordered = sorted((dict(game) for game in games), key=lambda row: (str(row["date"]), int(row["game_pk"])))
    scored: dict[int, list[float]] = defaultdict(list)
    allowed: dict[int, list[float]] = defaultdict(list)
    home_scored: dict[int, list[float]] = defaultdict(list)
    home_allowed: dict[int, list[float]] = defaultdict(list)
    away_scored: dict[int, list[float]] = defaultdict(list)
    away_allowed: dict[int, list[float]] = defaultdict(list)
    last_played: dict[int, str] = {}
    output: dict[str, list[dict[str, Any]]] = {name: [] for name in FEATURE_FAMILIES}

    for current_date, date_group in groupby(ordered, key=lambda row: str(row["date"])):
        day_games = list(date_group)
        for game in day_games:
            home = int(game["home_id"])
            away = int(game["away_id"])
            if len(scored[home]) < MLB_SIGNAL_MIN_PRIOR or len(scored[away]) < MLB_SIGNAL_MIN_PRIOR:
                continue

            home_rs30 = _mean_tail(scored[home], MLB_SIGNAL_LONG_WINDOW)
            home_ra30 = _mean_tail(allowed[home], MLB_SIGNAL_LONG_WINDOW)
            away_rs30 = _mean_tail(scored[away], MLB_SIGNAL_LONG_WINDOW)
            away_ra30 = _mean_tail(allowed[away], MLB_SIGNAL_LONG_WINDOW)
            home_rest = _day_gap(last_played, home, current_date)
            away_rest = _day_gap(last_played, away, current_date)
            values = {
                "home_rs_roll30": home_rs30,
                "home_ra_roll30": home_ra30,
                "away_rs_roll30": away_rs30,
                "away_ra_roll30": away_ra30,
                "home_net_roll30": home_rs30 - home_ra30,
                "away_net_roll30": away_rs30 - away_ra30,
                "home_rs_home_split30": _mean_tail(home_scored[home], MLB_SIGNAL_LONG_WINDOW),
                "away_rs_away_split30": _mean_tail(away_scored[away], MLB_SIGNAL_LONG_WINDOW),
                "home_rest_proxy": home_rest,
                "away_rest_proxy": away_rest,
                "rest_diff": home_rest - away_rest,
            }
            home_rs10 = _mean_tail(scored[home], MLB_SIGNAL_SHORT_WINDOW)
            home_ra10 = _mean_tail(allowed[home], MLB_SIGNAL_SHORT_WINDOW)
            away_rs10 = _mean_tail(scored[away], MLB_SIGNAL_SHORT_WINDOW)
            away_ra10 = _mean_tail(allowed[away], MLB_SIGNAL_SHORT_WINDOW)
            values.update({
                "home_rs_roll10": home_rs10,
                "home_ra_roll10": home_ra10,
                "away_rs_roll10": away_rs10,
                "away_ra_roll10": away_ra10,
                "home_net_roll10": home_rs10 - home_ra10,
                "away_net_roll10": away_rs10 - away_ra10,
                "home_ra_home_split30": _mean_tail(home_allowed[home], MLB_SIGNAL_LONG_WINDOW),
                "away_ra_away_split30": _mean_tail(away_allowed[away], MLB_SIGNAL_LONG_WINDOW),
            })
            try:
                home_score = float(game["home_score"])
                away_score = float(game["away_score"])
                season = int(current_date[:4])
            except (KeyError, TypeError, ValueError) as exc:
                raise MLBSignalResearchError("MLB_SIGNAL_DEV_GAME_INVALID") from exc
            if not all(isfinite(value) for value in values.values()):
                raise MLBSignalResearchError("MLB_SIGNAL_DEV_FEATURE_NONFINITE")
            common = {
                "date": current_date,
                "season": season,
                "game_pk": int(game["game_pk"]),
                "margin": home_score - away_score,
                "total": home_score + away_score,
            }
            for family, names in FEATURE_FAMILIES.items():
                output[family].append({**common, "features": [float(values[name]) for name in names]})

        for game in day_games:
            home = int(game["home_id"])
            away = int(game["away_id"])
            home_score = float(game["home_score"])
            away_score = float(game["away_score"])
            scored[home].append(home_score)
            allowed[home].append(away_score)
            scored[away].append(away_score)
            allowed[away].append(home_score)
            home_scored[home].append(home_score)
            home_allowed[home].append(away_score)
            away_scored[away].append(away_score)
            away_allowed[away].append(home_score)
            last_played[home] = last_played[away] = current_date

    identities = {
        family: [(row["date"], row["game_pk"], row["margin"], row["total"]) for row in rows]
        for family, rows in output.items()
    }
    first = identities["baseline_v1"]
    if any(rows != first for rows in identities.values()):
        raise MLBSignalResearchError("MLB_SIGNAL_DEV_FAMILY_ROW_IDENTITY_MISMATCH")
    if not first:
        raise MLBSignalResearchError("MLB_SIGNAL_DEV_NO_USABLE_ROWS")
    return output


def _standardize(train: np.ndarray, other: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mean = train.mean(axis=0)
    std = train.std(axis=0)
    std[std == 0] = 1.0
    return (train - mean) / std, (other - mean) / std


def _ridge_fit(X: np.ndarray, y: np.ndarray, alpha: float) -> tuple[np.ndarray, float]:
    centered_x = X - X.mean(axis=0)
    centered_y = y - y.mean()
    beta = np.linalg.solve(centered_x.T @ centered_x + float(alpha) * np.eye(X.shape[1]), centered_x.T @ centered_y)
    intercept = float(y.mean() - X.mean(axis=0) @ beta)
    return beta, intercept


def _cv_alpha(X: np.ndarray, y: np.ndarray, *, folds: int = 5) -> tuple[float, dict[str, float]]:
    if len(X) < 100:
        raise MLBSignalResearchError("MLB_SIGNAL_DEV_TRAIN_ROWS_INSUFFICIENT")
    scores: dict[float, list[float]] = {alpha: [] for alpha in MLB_SIGNAL_ALPHAS}
    n = len(X)
    for fold in range(1, folds + 1):
        cut = int(n * fold / (folds + 1))
        end = int(n * (fold + 1) / (folds + 1))
        if cut <= X.shape[1] or end <= cut:
            raise MLBSignalResearchError("MLB_SIGNAL_DEV_CV_FOLD_INVALID")
        X_train, X_valid = _standardize(X[:cut], X[cut:end])
        y_train, y_valid = y[:cut], y[cut:end]
        for alpha in MLB_SIGNAL_ALPHAS:
            beta, intercept = _ridge_fit(X_train, y_train, alpha)
            prediction = X_valid @ beta + intercept
            scores[alpha].append(float(np.mean((prediction - y_valid) ** 2)))
    means = {alpha: float(np.mean(values)) for alpha, values in scores.items()}
    selected = min(MLB_SIGNAL_ALPHAS, key=lambda alpha: (means[alpha], alpha))
    return float(selected), {str(alpha): means[alpha] for alpha in MLB_SIGNAL_ALPHAS}


def _arrays(rows: Sequence[Mapping[str, Any]], target: str) -> tuple[np.ndarray, np.ndarray]:
    X = np.asarray([row["features"] for row in rows], dtype=float)
    y = np.asarray([row[target] for row in rows], dtype=float)
    if X.ndim != 2 or len(X) != len(y):
        raise MLBSignalResearchError("MLB_SIGNAL_DEV_ARRAY_SHAPE_INVALID")
    return X, y


def _fit_evaluate(train_rows: Sequence[Mapping[str, Any]], valid_rows: Sequence[Mapping[str, Any]], target: str) -> dict[str, Any]:
    X_train, y_train = _arrays(train_rows, target)
    X_valid, y_valid = _arrays(valid_rows, target)
    alpha, cv_scores = _cv_alpha(X_train, y_train)
    X_train_s, X_valid_s = _standardize(X_train, X_valid)
    beta, intercept = _ridge_fit(X_train_s, y_train, alpha)
    prediction = X_valid_s @ beta + intercept
    mse = float(np.mean((prediction - y_valid) ** 2))
    baseline_mse = float(np.mean((float(y_train.mean()) - y_valid) ** 2))
    return {
        "selected_alpha": alpha,
        "alpha_cv_mse": cv_scores,
        "train_row_count": len(train_rows),
        "validation_row_count": len(valid_rows),
        "rmse": float(np.sqrt(mse)),
        "mean_baseline_rmse": float(np.sqrt(baseline_mse)),
        "r2_vs_train_mean": float(1.0 - mse / baseline_mse) if baseline_mse else 0.0,
        "mae": float(np.mean(np.abs(prediction - y_valid))),
        "coefficients_standardized": [float(value) for value in beta],
    }


def _season_partition(rows: Sequence[Mapping[str, Any]], validation_season: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    train = [dict(row) for row in rows if int(row["season"]) < validation_season]
    valid = [dict(row) for row in rows if int(row["season"]) == validation_season]
    if not train or not valid:
        raise MLBSignalResearchError(f"MLB_SIGNAL_DEV_PARTITION_EMPTY:{validation_season}")
    return train, valid


def evaluate_predeclared_families(feature_rows: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    """Select on 2023, then reveal only baseline + winner on 2024."""
    expected = set(FEATURE_FAMILIES)
    if set(feature_rows) != expected:
        raise MLBSignalResearchError("MLB_SIGNAL_DEV_FEATURE_FAMILIES_MISMATCH")

    selection: dict[str, Any] = {}
    for family in FEATURE_FAMILIES:
        train, valid = _season_partition(feature_rows[family], MLB_SIGNAL_SELECTION_SEASON)
        targets = {target: _fit_evaluate(train, valid, target) for target in ("margin", "total")}
        selection[family] = {
            "feature_names": list(FEATURE_FAMILIES[family]),
            "feature_count": len(FEATURE_FAMILIES[family]),
            "targets": targets,
            "selection_score_mean_rmse": float(np.mean([targets["margin"]["rmse"], targets["total"]["rmse"]])),
        }

    selected_family = min(
        FEATURE_FAMILIES,
        key=lambda family: (
            selection[family]["selection_score_mean_rmse"],
            selection[family]["feature_count"],
            family,
        ),
    )

    confirmation: dict[str, Any] = {}
    families_to_reveal = ["baseline_v1"] if selected_family == "baseline_v1" else ["baseline_v1", selected_family]
    for family in families_to_reveal:
        train, valid = _season_partition(feature_rows[family], MLB_SIGNAL_CONFIRMATION_SEASON)
        confirmation[family] = {
            "feature_names": list(FEATURE_FAMILIES[family]),
            "targets": {target: _fit_evaluate(train, valid, target) for target in ("margin", "total")},
        }

    deltas: dict[str, float] = {}
    if selected_family == "baseline_v1":
        deltas = {"margin": 0.0, "total": 0.0, "mean": 0.0}
        verdict = "NO_DEV_IMPROVEMENT_BASELINE_SELECTED"
    else:
        for target in ("margin", "total"):
            base = float(confirmation["baseline_v1"]["targets"][target]["rmse"])
            candidate = float(confirmation[selected_family]["targets"][target]["rmse"])
            deltas[target] = base - candidate
        deltas["mean"] = float(np.mean([deltas["margin"], deltas["total"]]))
        if deltas["margin"] > 0 and deltas["total"] > 0:
            verdict = "PROMISING_DEV_SIGNAL_BOTH_TARGETS"
        elif deltas["mean"] > 0:
            verdict = "MIXED_DEV_SIGNAL"
        else:
            verdict = "NO_DEV_CONFIRMATION"

    return {
        "research_version": MLB_SIGNAL_RESEARCH_VERSION,
        "selection_policy": {
            "feature_family_selection_season": MLB_SIGNAL_SELECTION_SEASON,
            "confirmation_season": MLB_SIGNAL_CONFIRMATION_SEASON,
            "selection_metric": "MEAN_OF_MARGIN_AND_TOTAL_RMSE",
            "selection_tie_break": "FEWER_FEATURES_THEN_FAMILY_NAME",
            "ridge_alpha_selection": "FORWARD_CHAINING_WITHIN_PRIOR_ROWS_ONLY",
            "confirmation_visibility": "ONLY_BASELINE_AND_2023_SELECTED_FAMILY",
            "sacred_2025_holdout_accessed": False,
        },
        "selection_2023": selection,
        "selected_family": selected_family,
        "confirmation_2024": confirmation,
        "confirmation_rmse_improvement_vs_baseline": deltas,
        "verdict": verdict,
        "promotion_evidence": False,
        "market_data_used": False,
    }


__all__ = [
    "FEATURE_FAMILIES",
    "MLB_SIGNAL_ALLOWED_SEASONS",
    "MLB_SIGNAL_CONFIRMATION_SEASON",
    "MLB_SIGNAL_RESEARCH_VERSION",
    "MLB_SIGNAL_SACRED_HOLDOUT_SEASON",
    "MLB_SIGNAL_SELECTION_SEASON",
    "MLBSignalResearchError",
    "build_feature_rows",
    "evaluate_predeclared_families",
    "validate_research_seasons",
]
