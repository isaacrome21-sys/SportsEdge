"""Frozen NFL play-level Attempt-1 residual challenger.

Implements the already-preregistered NFL_PLAY_LEVEL_EPA_CPOE_G1 Attempt 1
without acquiring or scoring the 2024 validation season itself.

Input rows are market-blind PIT feature snapshots with frozen Attempt-9 raw
margin/total means. Closing spread/total fields are accepted only by the
validation evaluator and are never included in a fit matrix.

Authority: research/shadow only. No Model_P, Truth Gate, OFFICIAL, promotion,
staking, or 2026 owner change.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import erf, isfinite, log, sqrt
from typing import Any, Mapping, Sequence

import numpy as np

FEATURE_NAMES = (
    "OFFENSE_EPA_PER_PLAY",
    "DEFENSE_EPA_ALLOWED_PER_PLAY",
    "OFFENSE_SUCCESS_RATE",
    "DEFENSE_SUCCESS_RATE_ALLOWED",
    "OFFENSE_PASS_EPA_PER_DROPBACK",
    "DEFENSE_PASS_EPA_ALLOWED_PER_DROPBACK",
    "OFFENSE_RUSH_EPA_PER_RUSH",
    "DEFENSE_RUSH_EPA_ALLOWED_PER_RUSH",
    "NEUTRAL_DOWN_PASS_OE_FROM_NFLVERSE_XPASS",
    "OFFENSIVE_PLAYS_PER_GAME_PACE",
    "STARTING_QB_DROPBACK_EPA_SHRUNK",
    "STARTING_QB_CPOE_SHRUNK",
)
ALPHA_GRID = (0.1, 1.0, 10.0, 100.0)
DEV_SEASONS = tuple(range(2016, 2024))
CV_SEASONS = (2019, 2020, 2021, 2022, 2023)
VALIDATION_SEASON = 2024
EPS = 1e-12
ECE_BINS = 10
SCHEMA = "SPORTSEDGE_NFL_PLAY_LEVEL_ATTEMPT1_FIT_V1"


class NflPlayLevelAttempt1Error(ValueError):
    pass


@dataclass(frozen=True)
class RidgeTarget:
    target: str
    alpha: float
    mean: tuple[float, ...]
    std: tuple[float, ...]
    coefficients: tuple[float, ...]
    intercept: float
    challenger_oof_sigma: float
    baseline_oof_sigma: float
    cv_rmse_by_alpha: Mapping[float, float]


@dataclass(frozen=True)
class Attempt1Model:
    schema: str
    feature_names: tuple[str, ...]
    development_seasons: tuple[int, ...]
    validation_season: int
    margin: RidgeTarget
    total: RidgeTarget
    authority: str = "RESEARCH_SHADOW_ONLY_NOT_MODEL_P"


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise NflPlayLevelAttempt1Error(f"{field}:NUMERIC_REQUIRED")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise NflPlayLevelAttempt1Error(f"{field}:NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise NflPlayLevelAttempt1Error(f"{field}:NONFINITE")
    return out


def _season(row: Mapping[str, Any]) -> int:
    raw = row.get("season")
    if isinstance(raw, bool):
        raise NflPlayLevelAttempt1Error("SEASON_INVALID")
    try:
        season = int(raw)
    except (TypeError, ValueError) as exc:
        raise NflPlayLevelAttempt1Error("SEASON_INVALID") from exc
    if raw != season:
        try:
            if float(raw) != season:
                raise NflPlayLevelAttempt1Error("SEASON_INVALID")
        except (TypeError, ValueError) as exc:
            raise NflPlayLevelAttempt1Error("SEASON_INVALID") from exc
    return season


def _feature_vector(row: Mapping[str, Any], *, target: str) -> np.ndarray:
    home = row.get("home_features")
    away = row.get("away_features")
    if not isinstance(home, Mapping) or not isinstance(away, Mapping):
        raise NflPlayLevelAttempt1Error("HOME_AWAY_FEATURE_OBJECTS_REQUIRED")
    expected = set(FEATURE_NAMES)
    if set(home) != expected or set(away) != expected:
        raise NflPlayLevelAttempt1Error("ATTEMPT1_FEATURE_SET_DRIFT")
    h = np.asarray([_number(home[name], f"home_features.{name}") for name in FEATURE_NAMES], dtype=float)
    a = np.asarray([_number(away[name], f"away_features.{name}") for name in FEATURE_NAMES], dtype=float)
    if target == "margin":
        return h - a
    if target == "total":
        return h + a
    raise NflPlayLevelAttempt1Error("TARGET_INVALID")


def _actual(row: Mapping[str, Any], target: str) -> float:
    field = "actual_margin" if target == "margin" else "actual_total"
    return _number(row.get(field), field)


def _baseline(row: Mapping[str, Any], target: str) -> float:
    field = "attempt9_margin" if target == "margin" else "attempt9_total"
    return _number(row.get(field), field)


def _matrix(rows: Sequence[Mapping[str, Any]], target: str) -> tuple[np.ndarray, np.ndarray]:
    if not rows:
        raise NflPlayLevelAttempt1Error("TRAINING_ROWS_EMPTY")
    x = np.vstack([_feature_vector(row, target=target) for row in rows])
    y = np.asarray([_actual(row, target) - _baseline(row, target) for row in rows], dtype=float)
    return x, y


def _fit_ridge(x: np.ndarray, y: np.ndarray, alpha: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    if x.ndim != 2 or y.ndim != 1 or len(x) != len(y) or len(x) < 2:
        raise NflPlayLevelAttempt1Error("RIDGE_TRAINING_SHAPE_INVALID")
    mean = x.mean(axis=0)
    std = x.std(axis=0)
    std = np.where(std <= 0, 1.0, std)
    z = (x - mean) / std
    z_mean = z.mean(axis=0)
    y_mean = float(y.mean())
    zc = z - z_mean
    yc = y - y_mean
    eye = np.eye(z.shape[1], dtype=float)
    beta = np.linalg.solve(zc.T @ zc + float(alpha) * eye, zc.T @ yc)
    intercept = float(y_mean - z_mean @ beta)
    return mean, std, beta, intercept


def _predict_residual(
    x: np.ndarray,
    mean: np.ndarray,
    std: np.ndarray,
    beta: np.ndarray,
    intercept: float,
) -> np.ndarray:
    return ((x - mean) / std) @ beta + intercept


def _rmse(pred: np.ndarray, actual: np.ndarray) -> float:
    if len(pred) == 0 or len(pred) != len(actual):
        raise NflPlayLevelAttempt1Error("RMSE_SHAPE_INVALID")
    return float(np.sqrt(np.mean((pred - actual) ** 2)))


def _cv_predictions(
    rows: Sequence[Mapping[str, Any]],
    *,
    target: str,
    alpha: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    challenger: list[float] = []
    baseline: list[float] = []
    actual: list[float] = []
    materialized = [dict(row) for row in rows]
    for year in CV_SEASONS:
        train = [row for row in materialized if _season(row) < year]
        valid = [row for row in materialized if _season(row) == year]
        if not train or not valid:
            raise NflPlayLevelAttempt1Error(f"CV_SEASON_ROWS_MISSING:{year}")
        x_train, y_train = _matrix(train, target)
        mean, std, beta, intercept = _fit_ridge(x_train, y_train, alpha)
        x_valid, _ = _matrix(valid, target)
        correction = _predict_residual(x_valid, mean, std, beta, intercept)
        base = np.asarray([_baseline(row, target) for row in valid], dtype=float)
        obs = np.asarray([_actual(row, target) for row in valid], dtype=float)
        challenger.extend((base + correction).tolist())
        baseline.extend(base.tolist())
        actual.extend(obs.tolist())
    return (
        np.asarray(challenger, dtype=float),
        np.asarray(baseline, dtype=float),
        np.asarray(actual, dtype=float),
    )


def _sigma(residuals: np.ndarray) -> float:
    if residuals.ndim != 1 or len(residuals) < 2:
        raise NflPlayLevelAttempt1Error("RESIDUAL_SIGMA_ROWS_INSUFFICIENT")
    value = float(np.sqrt(np.mean(residuals ** 2)))
    if not isfinite(value) or value <= 0:
        raise NflPlayLevelAttempt1Error("RESIDUAL_SIGMA_INVALID")
    return value


def _fit_target(rows: Sequence[Mapping[str, Any]], target: str) -> RidgeTarget:
    scores: dict[float, float] = {}
    oof_by_alpha: dict[float, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    for alpha in ALPHA_GRID:
        challenger, baseline, actual = _cv_predictions(rows, target=target, alpha=alpha)
        scores[alpha] = _rmse(challenger, actual)
        oof_by_alpha[alpha] = (challenger, baseline, actual)
    alpha = min(ALPHA_GRID, key=lambda value: (scores[value], value))
    challenger, baseline, actual = oof_by_alpha[alpha]
    challenger_sigma = _sigma(actual - challenger)
    baseline_sigma = _sigma(actual - baseline)

    x, y = _matrix(rows, target)
    mean, std, beta, intercept = _fit_ridge(x, y, alpha)
    return RidgeTarget(
        target=target,
        alpha=float(alpha),
        mean=tuple(float(v) for v in mean),
        std=tuple(float(v) for v in std),
        coefficients=tuple(float(v) for v in beta),
        intercept=float(intercept),
        challenger_oof_sigma=challenger_sigma,
        baseline_oof_sigma=baseline_sigma,
        cv_rmse_by_alpha={float(k): float(v) for k, v in scores.items()},
    )


def fit_attempt1(rows: Sequence[Mapping[str, Any]]) -> Attempt1Model:
    materialized = [dict(row) for row in rows]
    seasons = {_season(row) for row in materialized}
    if not seasons:
        raise NflPlayLevelAttempt1Error("TRAINING_ROWS_EMPTY")
    if not seasons.issubset(set(DEV_SEASONS)):
        raise NflPlayLevelAttempt1Error(f"DEVELOPMENT_SEASON_LEAK:{sorted(seasons - set(DEV_SEASONS))}")
    missing = set(CV_SEASONS) - seasons
    if missing:
        raise NflPlayLevelAttempt1Error(f"DEVELOPMENT_CV_SEASONS_MISSING:{sorted(missing)}")
    return Attempt1Model(
        schema=SCHEMA,
        feature_names=FEATURE_NAMES,
        development_seasons=DEV_SEASONS,
        validation_season=VALIDATION_SEASON,
        margin=_fit_target(materialized, "margin"),
        total=_fit_target(materialized, "total"),
    )


def _target_model(model: Attempt1Model, target: str) -> RidgeTarget:
    if target == "margin":
        return model.margin
    if target == "total":
        return model.total
    raise NflPlayLevelAttempt1Error("TARGET_INVALID")


def predict_mean(model: Attempt1Model, row: Mapping[str, Any], target: str) -> float:
    target_model = _target_model(model, target)
    x = _feature_vector(row, target=target).reshape(1, -1)
    correction = _predict_residual(
        x,
        np.asarray(target_model.mean),
        np.asarray(target_model.std),
        np.asarray(target_model.coefficients),
        target_model.intercept,
    )[0]
    return float(_baseline(row, target) + correction)


def _normal_cdf(x: float, mean: float, sigma: float) -> float:
    return 0.5 * (1.0 + erf((x - mean) / (sigma * sqrt(2.0))))


def _prob_over_threshold(mean: float, threshold: float, sigma: float) -> float:
    p = 1.0 - _normal_cdf(threshold, mean, sigma)
    return min(1.0 - EPS, max(EPS, p))


def _half_point(value: Any, field: str) -> float:
    line = _number(value, field)
    doubled = line * 2.0
    if abs(doubled - round(doubled)) > 1e-9 or abs(line - round(line)) < 1e-9:
        raise NflPlayLevelAttempt1Error(f"{field}:HALF_POINT_REQUIRED")
    return line


def _log_loss(probabilities: np.ndarray, outcomes: np.ndarray) -> float:
    if len(probabilities) == 0 or len(probabilities) != len(outcomes):
        raise NflPlayLevelAttempt1Error("LOG_LOSS_SHAPE_INVALID")
    p = np.clip(probabilities.astype(float), EPS, 1.0 - EPS)
    y = outcomes.astype(float)
    return float(-np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))


def _calibration(probabilities: np.ndarray, outcomes: np.ndarray) -> dict[str, float]:
    if len(probabilities) < 2:
        raise NflPlayLevelAttempt1Error("CALIBRATION_ROWS_INSUFFICIENT")
    p = probabilities.astype(float)
    y = outcomes.astype(float)
    mean_p = float(p.mean())
    mean_y = float(y.mean())
    denom = float(np.sum((p - mean_p) ** 2))
    if denom <= 0:
        slope = float("nan")
        intercept = float("nan")
    else:
        slope = float(np.sum((p - mean_p) * (y - mean_y)) / denom)
        intercept = mean_y - slope * mean_p
    ece = 0.0
    for index in range(ECE_BINS):
        lo = index / ECE_BINS
        hi = (index + 1) / ECE_BINS
        mask = (p >= lo) & (p < hi if index < ECE_BINS - 1 else p <= hi)
        count = int(mask.sum())
        if count:
            ece += (count / len(p)) * abs(float(p[mask].mean()) - float(y[mask].mean()))
    return {"slope": slope, "intercept": intercept, "ece": float(ece)}


def evaluate_2024(
    model: Attempt1Model,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    materialized = [dict(row) for row in rows]
    if not materialized:
        raise NflPlayLevelAttempt1Error("VALIDATION_ROWS_EMPTY")
    seasons = {_season(row) for row in materialized}
    if seasons != {VALIDATION_SEASON}:
        raise NflPlayLevelAttempt1Error(f"VALIDATION_SEASON_INVALID:{sorted(seasons)}")

    challenger_margin: list[float] = []
    challenger_total: list[float] = []
    baseline_margin: list[float] = []
    baseline_total: list[float] = []
    actual_margin: list[float] = []
    actual_total: list[float] = []
    challenger_spread_p: list[float] = []
    baseline_spread_p: list[float] = []
    spread_y: list[int] = []
    challenger_total_p: list[float] = []
    baseline_total_p: list[float] = []
    total_y: list[int] = []

    for row in materialized:
        home_handicap = _half_point(row.get("close_home_handicap"), "close_home_handicap")
        total_line = _half_point(row.get("close_total"), "close_total")
        actual_m = _actual(row, "margin")
        actual_t = _actual(row, "total")
        base_m = _baseline(row, "margin")
        base_t = _baseline(row, "total")
        cand_m = predict_mean(model, row, "margin")
        cand_t = predict_mean(model, row, "total")

        challenger_margin.append(cand_m)
        challenger_total.append(cand_t)
        baseline_margin.append(base_m)
        baseline_total.append(base_t)
        actual_margin.append(actual_m)
        actual_total.append(actual_t)

        spread_threshold = -home_handicap
        challenger_spread_p.append(
            _prob_over_threshold(cand_m, spread_threshold, model.margin.challenger_oof_sigma)
        )
        baseline_spread_p.append(
            _prob_over_threshold(base_m, spread_threshold, model.margin.baseline_oof_sigma)
        )
        spread_y.append(1 if actual_m > spread_threshold else 0)

        challenger_total_p.append(
            _prob_over_threshold(cand_t, total_line, model.total.challenger_oof_sigma)
        )
        baseline_total_p.append(
            _prob_over_threshold(base_t, total_line, model.total.baseline_oof_sigma)
        )
        total_y.append(1 if actual_t > total_line else 0)

    cm = np.asarray(challenger_margin)
    ct = np.asarray(challenger_total)
    bm = np.asarray(baseline_margin)
    bt = np.asarray(baseline_total)
    am = np.asarray(actual_margin)
    at = np.asarray(actual_total)
    csp = np.asarray(challenger_spread_p)
    bsp = np.asarray(baseline_spread_p)
    sy = np.asarray(spread_y)
    ctp = np.asarray(challenger_total_p)
    btp = np.asarray(baseline_total_p)
    ty = np.asarray(total_y)

    c_spread_ll = _log_loss(csp, sy)
    b_spread_ll = _log_loss(bsp, sy)
    c_total_ll = _log_loss(ctp, ty)
    b_total_ll = _log_loss(btp, ty)
    c_pool = 0.5 * (c_spread_ll + c_total_ll)
    b_pool = 0.5 * (b_spread_ll + b_total_ll)
    cal_spread = _calibration(csp, sy)
    cal_total = _calibration(ctp, ty)

    gates = {
        "pooled_log_loss_beats_attempt9": c_pool < b_pool,
        "margin_log_loss_max_regression": (c_spread_ll - b_spread_ll) <= 0.002 + EPS,
        "total_log_loss_max_regression": (c_total_ll - b_total_ll) <= 0.002 + EPS,
        "one_market_improves_log_loss_by_0_005": (
            (b_spread_ll - c_spread_ll) >= 0.005 - EPS
            or (b_total_ll - c_total_ll) >= 0.005 - EPS
        ),
        "margin_rmse_not_worse": _rmse(cm, am) <= _rmse(bm, am) + EPS,
        "total_rmse_not_worse": _rmse(ct, at) <= _rmse(bt, at) + EPS,
        "spread_calibration": (
            0.90 <= cal_spread["slope"] <= 1.10
            and abs(cal_spread["intercept"]) <= 0.03
            and cal_spread["ece"] <= 0.025
        ),
        "total_calibration": (
            0.90 <= cal_total["slope"] <= 1.10
            and abs(cal_total["intercept"]) <= 0.03
            and cal_total["ece"] <= 0.025
        ),
    }

    return {
        "schema": "SPORTSEDGE_NFL_PLAY_LEVEL_ATTEMPT1_2024_EVAL_V1",
        "attempt_id": "NFL_PLAY_LEVEL_EPA_CPOE_G1_ATTEMPT_1",
        "validation_season": VALIDATION_SEASON,
        "n": len(materialized),
        "comparison_rows": "IDENTICAL_HALF_POINT_GAME_MARKET_ROWS",
        "candidate": {
            "spread_log_loss": c_spread_ll,
            "total_log_loss": c_total_ll,
            "pooled_log_loss": c_pool,
            "margin_rmse": _rmse(cm, am),
            "total_rmse": _rmse(ct, at),
            "spread_calibration": cal_spread,
            "total_calibration": cal_total,
        },
        "attempt9": {
            "spread_log_loss": b_spread_ll,
            "total_log_loss": b_total_ll,
            "pooled_log_loss": b_pool,
            "margin_rmse": _rmse(bm, am),
            "total_rmse": _rmse(bt, at),
        },
        "gates": gates,
        "pass": all(gates.values()),
        "diagnostic_2025_can_rescue": False,
        "authority": "RESEARCH_SHADOW_ONLY_NOT_MODEL_P",
    }


__all__ = [
    "ALPHA_GRID",
    "Attempt1Model",
    "CV_SEASONS",
    "DEV_SEASONS",
    "FEATURE_NAMES",
    "NflPlayLevelAttempt1Error",
    "RidgeTarget",
    "evaluate_2024",
    "fit_attempt1",
    "predict_mean",
]
