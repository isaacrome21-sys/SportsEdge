"""CFB v1.2 chronological validation and calibration contracts.

The calibrator is trained only on inner out-of-fold predictions from seasons strictly
before the outer held-out season. Raw and calibrated metrics are both retained.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite, log, sqrt
from statistics import mean
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from sportsedge.core.calibrate.isotonic import FoldSafeIsotonicCalibrator


class CFBValidationError(ValueError):
    pass


def _prob(value: Any, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise CFBValidationError(f"{field}:NUMERIC_REQUIRED") from exc
    if not isfinite(out) or not 0.0 <= out <= 1.0:
        raise CFBValidationError(f"{field}:PROBABILITY_RANGE")
    return out


def _binary(value: Any) -> int:
    if value in (0, 0.0, False):
        return 0
    if value in (1, 1.0, True):
        return 1
    raise CFBValidationError("OUTCOME_BINARY_REQUIRED")


def _clip(p: float, eps: float = 1e-12) -> float:
    return min(1.0 - eps, max(eps, float(p)))


def brier_score(probs: Sequence[float], outcomes: Sequence[int]) -> float:
    if len(probs) != len(outcomes) or not probs:
        raise CFBValidationError("METRIC_LENGTH_INVALID")
    return sum((_prob(p, "prob") - _binary(y)) ** 2 for p, y in zip(probs, outcomes)) / len(probs)


def log_loss(probs: Sequence[float], outcomes: Sequence[int]) -> float:
    if len(probs) != len(outcomes) or not probs:
        raise CFBValidationError("METRIC_LENGTH_INVALID")
    total = 0.0
    for p, y in zip(probs, outcomes):
        value = _clip(_prob(p, "prob"))
        target = _binary(y)
        total += -(target * log(value) + (1 - target) * log(1.0 - value))
    return total / len(probs)


def expected_calibration_error(probs: Sequence[float], outcomes: Sequence[int], *, bins: int = 10) -> float:
    if len(probs) != len(outcomes) or not probs:
        raise CFBValidationError("METRIC_LENGTH_INVALID")
    if isinstance(bins, bool) or int(bins) <= 1:
        raise CFBValidationError("ECE_BINS_INVALID")
    bucket_count = int(bins)
    groups: list[list[tuple[float, int]]] = [[] for _ in range(bucket_count)]
    for p, y in zip(probs, outcomes):
        value = _prob(p, "prob")
        idx = min(bucket_count - 1, int(value * bucket_count))
        groups[idx].append((value, _binary(y)))
    n = len(probs)
    return sum(
        (len(group) / n) * abs(mean(p for p, _ in group) - mean(y for _, y in group))
        for group in groups if group
    )


def calibration_intercept_slope(probs: Sequence[float], outcomes: Sequence[int]) -> tuple[float, float]:
    """Fit logistic calibration intercept/slope: y ~ 1 + logit(p)."""

    if len(probs) != len(outcomes) or len(probs) < 10:
        raise CFBValidationError("CALIBRATION_SAMPLE_INSUFFICIENT")
    x = np.asarray([log(_clip(_prob(p, "prob")) / (1.0 - _clip(_prob(p, "prob")))) for p in probs], dtype=float)
    y = np.asarray([_binary(v) for v in outcomes], dtype=float)
    design = np.column_stack((np.ones(len(x), dtype=float), x))
    beta = np.asarray([0.0, 1.0], dtype=float)
    ridge = np.diag([1e-8, 1e-8])
    for _ in range(50):
        eta = design @ beta
        eta = np.clip(eta, -30.0, 30.0)
        mu = 1.0 / (1.0 + np.exp(-eta))
        weights = np.maximum(mu * (1.0 - mu), 1e-8)
        gradient = design.T @ (y - mu) - ridge @ beta
        hessian = -(design.T @ (weights[:, None] * design) + ridge)
        try:
            step = np.linalg.solve(hessian, gradient)
        except np.linalg.LinAlgError:
            step = np.linalg.pinv(hessian) @ gradient
        beta_next = beta - step
        if float(np.max(np.abs(beta_next - beta))) < 1e-9:
            beta = beta_next
            break
        beta = beta_next
    intercept, slope = float(beta[0]), float(beta[1])
    if not isfinite(intercept) or not isfinite(slope):
        raise CFBValidationError("CALIBRATION_FIT_NONFINITE")
    return intercept, slope


@dataclass(frozen=True)
class ProbabilityMetrics:
    n: int
    brier: float
    logloss: float
    ece: float
    calibration_intercept: float
    calibration_slope: float


def probability_metrics(probs: Sequence[float], outcomes: Sequence[int]) -> ProbabilityMetrics:
    intercept, slope = calibration_intercept_slope(probs, outcomes)
    return ProbabilityMetrics(
        n=len(probs),
        brier=brier_score(probs, outcomes),
        logloss=log_loss(probs, outcomes),
        ece=expected_calibration_error(probs, outcomes),
        calibration_intercept=intercept,
        calibration_slope=slope,
    )


@dataclass(frozen=True)
class CalibratedFold:
    test_season: int
    market: str
    raw_metrics: ProbabilityMetrics
    calibrated_metrics: ProbabilityMetrics
    benchmark_metrics: ProbabilityMetrics
    calibrated_rows: tuple[dict[str, Any], ...]


def nested_chronological_calibration(
    rows: Iterable[Mapping[str, Any]],
    *,
    test_season: int,
    market: str,
    raw_prob_key: str = "raw_model_prob",
    benchmark_prob_key: str = "benchmark_prob",
    outcome_key: str = "outcome",
) -> CalibratedFold:
    """Calibrate one untouched outer test season using prior inner OOF predictions.

    Contract for every row:
    - ``season`` is the prediction season.
    - ``model_train_max_season`` is the latest season used to fit the model that emitted
      ``raw_model_prob``. It must be strictly less than the prediction season.
    - training rows for the calibrator must all precede ``test_season``.
    """

    target_market = str(market).upper()
    data = [dict(row) for row in rows if str(row.get("market") or "").upper() == target_market]
    if not data:
        raise CFBValidationError("CALIBRATION_MARKET_ROWS_REQUIRED")
    inner: list[dict[str, Any]] = []
    outer: list[dict[str, Any]] = []
    for row in data:
        season = int(row["season"])
        train_max = int(row["model_train_max_season"])
        if train_max >= season:
            raise CFBValidationError(f"RAW_PREDICTION_NOT_OOF:{season}")
        if season < int(test_season):
            inner.append(row)
        elif season == int(test_season):
            outer.append(row)
        else:
            raise CFBValidationError("FUTURE_SEASON_PRESENT_IN_OUTER_FOLD")
    if len(inner) < 20 or len(outer) < 10:
        raise CFBValidationError("CALIBRATION_FOLD_SAMPLE_INSUFFICIENT")
    fit_seasons = {int(row["season"]) for row in inner}
    calibrator = FoldSafeIsotonicCalibrator().fit(
        [_prob(row[raw_prob_key], raw_prob_key) for row in inner],
        [_binary(row[outcome_key]) for row in inner],
        fit_seasons=fit_seasons,
        test_season=int(test_season),
    )
    raw = [_prob(row[raw_prob_key], raw_prob_key) for row in outer]
    calibrated = calibrator.transform(raw)
    benchmark = [_prob(row[benchmark_prob_key], benchmark_prob_key) for row in outer]
    outcomes = [_binary(row[outcome_key]) for row in outer]
    enriched = []
    for row, calibrated_p in zip(outer, calibrated):
        item = dict(row)
        item["calibrated_model_prob"] = float(calibrated_p)
        enriched.append(item)
    return CalibratedFold(
        test_season=int(test_season),
        market=target_market,
        raw_metrics=probability_metrics(raw, outcomes),
        calibrated_metrics=probability_metrics(calibrated, outcomes),
        benchmark_metrics=probability_metrics(benchmark, outcomes),
        calibrated_rows=tuple(enriched),
    )


def segmented_metrics(
    rows: Iterable[Mapping[str, Any]],
    *,
    prob_key: str = "calibrated_model_prob",
    outcome_key: str = "outcome",
) -> dict[str, ProbabilityMetrics]:
    """Required regime reporting: early week, conference class and favorite-size buckets."""

    groups: dict[str, list[dict[str, Any]]] = {}
    for source in rows:
        row = dict(source)
        week = int(row.get("week", 0))
        conf = str(row.get("conference_strength_bucket") or "UNKNOWN").upper()
        favorite_size = abs(float(row.get("favorite_size", 0.0)))
        week_key = f"WEEK_{week}" if 1 <= week <= 4 else "WEEK_5_PLUS"
        fav_key = "FAV_0_3" if favorite_size <= 3 else "FAV_3_7" if favorite_size <= 7 else "FAV_7_14" if favorite_size <= 14 else "FAV_14_PLUS"
        for key in (week_key, f"CONF_{conf}", fav_key):
            groups.setdefault(key, []).append(row)
    report: dict[str, ProbabilityMetrics] = {}
    for key, group in sorted(groups.items()):
        if len(group) < 10:
            continue
        report[key] = probability_metrics(
            [_prob(row[prob_key], prob_key) for row in group],
            [_binary(row[outcome_key]) for row in group],
        )
    return report


@dataclass(frozen=True)
class CoefficientStability:
    feature: str
    seasons: tuple[int, ...]
    coefficients: tuple[float, ...]
    sign_consistency: float
    magnitude_cv: float


def coefficient_stability(rows: Iterable[Mapping[str, Any]]) -> tuple[CoefficientStability, ...]:
    """Monitor sign/magnitude drift without treating stability as proof of predictive skill."""

    data = [dict(row) for row in rows]
    grouped: dict[str, list[tuple[int, float]]] = {}
    for row in data:
        feature = str(row.get("feature") or "").strip()
        if not feature:
            raise CFBValidationError("COEFFICIENT_FEATURE_REQUIRED")
        value = float(row["coefficient"])
        if not isfinite(value):
            raise CFBValidationError("COEFFICIENT_NONFINITE")
        grouped.setdefault(feature, []).append((int(row["test_season"]), value))
    out = []
    for feature, values in sorted(grouped.items()):
        ordered = sorted(values)
        coeffs = np.asarray([value for _, value in ordered], dtype=float)
        nonzero = coeffs[np.abs(coeffs) > 1e-12]
        if len(nonzero):
            positive = float(np.mean(nonzero > 0))
            sign_consistency = max(positive, 1.0 - positive)
        else:
            sign_consistency = 1.0
        abs_mean = float(np.mean(np.abs(coeffs)))
        magnitude_cv = 0.0 if abs_mean <= 1e-12 else float(np.std(coeffs) / abs_mean)
        out.append(CoefficientStability(
            feature=feature,
            seasons=tuple(season for season, _ in ordered),
            coefficients=tuple(float(x) for x in coeffs),
            sign_consistency=sign_consistency,
            magnitude_cv=magnitude_cv,
        ))
    return tuple(out)
