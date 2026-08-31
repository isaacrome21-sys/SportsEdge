"""Regularized heteroskedastic variance candidate for CFB score distributions.

This module does not promote itself. It is fit on training-only residuals and must beat
an unconditional residual baseline out of sample before the joint simulator may adopt it.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from math import exp, isfinite, log
from typing import Any, Iterable, Mapping

import numpy as np


VARIANCE_MODEL_ID = "CFB_HETEROSKEDASTIC_RIDGE_V1"
VARIANCE_FEATURES = (
    "projected_total",
    "expected_pace",
    "favorite_size",
    "qb_uncertainty",
    "explosiveness_differential",
)


class CFBVarianceError(ValueError):
    pass


def _num(value: Any, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise CFBVarianceError(f"{field}:NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise CFBVarianceError(f"{field}:FINITE_REQUIRED")
    return out


def _x(row: Mapping[str, Any]) -> np.ndarray:
    return np.asarray([_num(row.get(field), field) for field in VARIANCE_FEATURES], dtype=float)


def _ridge(design: np.ndarray, target: np.ndarray, alpha: float) -> np.ndarray:
    penalty = np.eye(design.shape[1], dtype=float) * float(alpha)
    penalty[0, 0] = 0.0
    lhs = design.T @ design + penalty
    rhs = design.T @ target
    try:
        return np.linalg.solve(lhs, rhs)
    except np.linalg.LinAlgError:
        return np.linalg.pinv(lhs) @ rhs


@dataclass(frozen=True)
class CFBVarianceModel:
    model_id: str
    feature_names: tuple[str, ...]
    feature_means: tuple[float, ...]
    feature_scales: tuple[float, ...]
    margin_logvar_coefficients: tuple[float, ...]
    total_logvar_coefficients: tuple[float, ...]
    training_seasons: tuple[int, ...]
    ridge_alpha: float
    epsilon: float

    def _design(self, row: Mapping[str, Any]) -> np.ndarray:
        raw = _x(row)
        means = np.asarray(self.feature_means, dtype=float)
        scales = np.asarray(self.feature_scales, dtype=float)
        if raw.shape != means.shape:
            raise CFBVarianceError("VARIANCE_FEATURE_DIMENSION_MISMATCH")
        return np.concatenate(([1.0], (raw - means) / scales))

    def predict_variances(self, row: Mapping[str, Any]) -> tuple[float, float]:
        design = self._design(row)
        margin = exp(float(design @ np.asarray(self.margin_logvar_coefficients, dtype=float)))
        total = exp(float(design @ np.asarray(self.total_logvar_coefficients, dtype=float)))
        if not isfinite(margin) or not isfinite(total) or margin <= 0.0 or total <= 0.0:
            raise CFBVarianceError("VARIANCE_PREDICTION_INVALID")
        return margin, total

    def content_hash(self) -> str:
        raw = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        return sha256(raw).hexdigest()


def fit_cfb_variance_model(
    rows: Iterable[Mapping[str, Any]],
    *,
    test_season: int,
    ridge_alpha: float = 20.0,
    epsilon: float = 1.0,
) -> CFBVarianceModel:
    """Fit log residual variance using training-only predictions/residuals.

    Each row must contain ``season``, the five variance features,
    ``margin_residual`` and ``total_residual``. Residuals must have been produced by a
    mean model that itself did not train on that observation.
    """

    data = [dict(row) for row in rows]
    if len(data) < 50:
        raise CFBVarianceError("VARIANCE_TRAINING_ROWS_INSUFFICIENT")
    seasons = tuple(sorted({int(row["season"]) for row in data}))
    if int(test_season) in seasons:
        raise CFBVarianceError("VARIANCE_TEST_SEASON_IN_TRAINING")
    alpha = _num(ridge_alpha, "ridge_alpha")
    eps = _num(epsilon, "epsilon")
    if alpha < 0.0 or eps <= 0.0:
        raise CFBVarianceError("VARIANCE_HYPERPARAMETER_INVALID")
    raw = np.asarray([_x(row) for row in data], dtype=float)
    means = raw.mean(axis=0)
    scales = raw.std(axis=0)
    scales = np.where(scales > 1e-12, scales, 1.0)
    design = np.column_stack((np.ones(len(data), dtype=float), (raw - means) / scales))
    margin_target = np.asarray([
        log(_num(row.get("margin_residual"), "margin_residual") ** 2 + eps)
        for row in data
    ], dtype=float)
    total_target = np.asarray([
        log(_num(row.get("total_residual"), "total_residual") ** 2 + eps)
        for row in data
    ], dtype=float)
    return CFBVarianceModel(
        model_id=VARIANCE_MODEL_ID,
        feature_names=VARIANCE_FEATURES,
        feature_means=tuple(map(float, means)),
        feature_scales=tuple(map(float, scales)),
        margin_logvar_coefficients=tuple(map(float, _ridge(design, margin_target, alpha))),
        total_logvar_coefficients=tuple(map(float, _ridge(design, total_target, alpha))),
        training_seasons=seasons,
        ridge_alpha=alpha,
        epsilon=eps,
    )


def variance_oos_score(rows: Iterable[Mapping[str, Any]], model: CFBVarianceModel) -> dict[str, float]:
    """Gaussian residual NLL diagnostic used only to compare variance candidates."""

    data = [dict(row) for row in rows]
    if not data:
        raise CFBVarianceError("VARIANCE_EVALUATION_ROWS_REQUIRED")
    margin_nll = 0.0
    total_nll = 0.0
    for row in data:
        margin_var, total_var = model.predict_variances(row)
        mr = _num(row.get("margin_residual"), "margin_residual")
        tr = _num(row.get("total_residual"), "total_residual")
        margin_nll += 0.5 * (log(margin_var) + mr * mr / margin_var)
        total_nll += 0.5 * (log(total_var) + tr * tr / total_var)
    return {
        "n": float(len(data)),
        "margin_mean_gaussian_nll": margin_nll / len(data),
        "total_mean_gaussian_nll": total_nll / len(data),
    }
