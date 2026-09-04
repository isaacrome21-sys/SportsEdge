"""Research-only nonlinear NFL M2 challenger.

The canonical NFL M2 remains the production ridge model. This challenger uses the
same market-blind M2 feature contract but expands it with bounded quadratic,
hinge and selected football matchup interactions before ridge fitting. The goal is
to test whether nonlinear structure improves chronological OOS probability quality
without adding an XGBoost dependency to production.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt
from typing import Any, Iterable

import numpy as np

from sportsedge.sports.nfl.m2 import (
    NFL_M2_FEATURE_CONTRACT,
    _MODEL_FEATURES,
    _game_feature_vector,
    _reconcile_scores,
    _target_scores,
    price_nfl_m2_game_markets,
)

NFL_M2_NONLINEAR_MODEL_ID = "nfl_m2_nonlinear_basis_ridge_v1_candidate"
NFL_M2_NONLINEAR_BASIS_VERSION = "NFL_M2_NONLINEAR_BASIS_V1"


class NFLM2NonlinearCandidateError(ValueError):
    pass


def _base_names() -> tuple[str, ...]:
    return tuple([f"home_{name}" for name in _MODEL_FEATURES] + [f"away_{name}" for name in _MODEL_FEATURES])


def _interaction_pairs(names: tuple[str, ...]) -> tuple[tuple[int, int, str], ...]:
    index = {name: i for i, name in enumerate(names)}
    requested = (
        ("home_adj_off_epa", "away_adj_def_epa", "home_off_x_away_def"),
        ("away_adj_off_epa", "home_adj_def_epa", "away_off_x_home_def"),
        ("home_pass_epa", "away_pressure_for", "home_pass_x_away_pressure"),
        ("away_pass_epa", "home_pressure_for", "away_pass_x_home_pressure"),
        ("home_qb_adjustment", "away_pressure_for", "home_qb_x_away_pressure"),
        ("away_qb_adjustment", "home_pressure_for", "away_qb_x_home_pressure"),
        ("home_rush_epa", "away_adj_def_epa", "home_rush_x_away_def"),
        ("away_rush_epa", "home_adj_def_epa", "away_rush_x_home_def"),
        ("home_explosive_rate", "away_adj_def_epa", "home_explosive_x_away_def"),
        ("away_explosive_rate", "home_adj_def_epa", "away_explosive_x_home_def"),
        ("home_pass_epa", "home_wind_mph", "home_pass_x_wind"),
        ("away_pass_epa", "away_wind_mph", "away_pass_x_wind"),
        ("home_qb_adjustment", "home_pressure_allowed", "home_qb_x_pressure_allowed"),
        ("away_qb_adjustment", "away_pressure_allowed", "away_qb_x_pressure_allowed"),
        ("home_positional_target_matchup_pressure", "away_adj_def_epa", "home_usage_x_def"),
        ("away_positional_target_matchup_pressure", "home_adj_def_epa", "away_usage_x_def"),
    )
    out = []
    for left, right, label in requested:
        if left in index and right in index:
            out.append((index[left], index[right], label))
    return tuple(out)


def _basis_names() -> tuple[str, ...]:
    base = _base_names()
    names = list(base)
    names += [f"sq_{name}" for name in base]
    names += [f"hinge_pos_{name}" for name in base]
    names += [f"hinge_neg_{name}" for name in base]
    names += [label for _, _, label in _interaction_pairs(base)]
    return tuple(names)


def _basis_from_standardized(z: np.ndarray) -> np.ndarray:
    if z.ndim != 1:
        raise NFLM2NonlinearCandidateError("STANDARDIZED_VECTOR_MUST_BE_1D")
    clipped = np.clip(z, -3.0, 3.0)
    squares = clipped * clipped
    hinge_pos = np.maximum(0.0, clipped - 1.0)
    hinge_neg = np.maximum(0.0, -clipped - 1.0)
    interactions = [clipped[i] * clipped[j] for i, j, _ in _interaction_pairs(_base_names())]
    return np.asarray([*clipped.tolist(), *squares.tolist(), *hinge_pos.tolist(), *hinge_neg.tolist(), *interactions], dtype=float)


def _ridge(design: np.ndarray, target: np.ndarray, alpha: float) -> np.ndarray:
    penalty = np.eye(design.shape[1], dtype=float) * alpha
    penalty[0, 0] = 0.0
    lhs = design.T @ design + penalty
    rhs = design.T @ target
    try:
        return np.linalg.solve(lhs, rhs)
    except np.linalg.LinAlgError:
        return np.linalg.pinv(lhs) @ rhs


@dataclass(frozen=True)
class NFLM2NonlinearModel:
    model_id: str
    feature_contract: str
    basis_version: str
    base_feature_names: tuple[str, ...]
    basis_feature_names: tuple[str, ...]
    base_means: tuple[float, ...]
    base_scales: tuple[float, ...]
    margin_coefficients: tuple[float, ...]
    total_coefficients: tuple[float, ...]
    residual_pairs: tuple[tuple[float, float], ...]
    train_seasons: tuple[int, ...]
    ridge_alpha: float
    margin_sigma: float
    total_sigma: float

    def predict(self, row: dict[str, Any]) -> tuple[float, float]:
        raw = np.asarray(_game_feature_vector(dict(row)), dtype=float)
        means = np.asarray(self.base_means, dtype=float)
        scales = np.asarray(self.base_scales, dtype=float)
        if raw.shape != means.shape:
            raise NFLM2NonlinearCandidateError("FEATURE_DIMENSION_MISMATCH")
        z = (raw - means) / scales
        basis = _basis_from_standardized(z)
        design = np.concatenate(([1.0], basis))
        margin = float(design @ np.asarray(self.margin_coefficients, dtype=float))
        total = float(design @ np.asarray(self.total_coefficients, dtype=float))
        if not isfinite(margin) or not isfinite(total):
            raise NFLM2NonlinearCandidateError("PREDICTION_NONFINITE")
        return margin, total


def fit_nfl_m2_nonlinear_candidate(
    rows: Iterable[dict[str, Any]], *,
    ridge_alpha: float = 50.0,
    min_rows: int = 200,
) -> NFLM2NonlinearModel:
    data = [dict(row) for row in rows]
    if len(data) < int(min_rows):
        raise NFLM2NonlinearCandidateError(f"TRAINING_ROWS_INSUFFICIENT:{len(data)}<{int(min_rows)}")
    alpha = float(ridge_alpha)
    if not isfinite(alpha) or alpha < 0:
        raise NFLM2NonlinearCandidateError("RIDGE_ALPHA_INVALID")
    raw = np.asarray([_game_feature_vector(row) for row in data], dtype=float)
    means = raw.mean(axis=0)
    scales = raw.std(axis=0)
    scales = np.where(scales > 1e-12, scales, 1.0)
    basis = np.asarray([_basis_from_standardized((row - means) / scales) for row in raw], dtype=float)
    design = np.column_stack((np.ones(len(data)), basis))
    targets = [_target_scores(row) for row in data]
    margin_y = np.asarray([target[0] for target in targets], dtype=float)
    total_y = np.asarray([target[1] for target in targets], dtype=float)
    margin_coef = _ridge(design, margin_y, alpha)
    total_coef = _ridge(design, total_y, alpha)
    margin_resid = margin_y - design @ margin_coef
    total_resid = total_y - design @ total_coef
    margin_sigma = float(sqrt(float(np.mean(margin_resid ** 2))))
    total_sigma = float(sqrt(float(np.mean(total_resid ** 2))))
    if margin_sigma <= 1e-12 or total_sigma <= 1e-12:
        raise NFLM2NonlinearCandidateError("RESIDUAL_SIGMA_ZERO")
    seasons = tuple(sorted({int(row["season"]) for row in data}))
    return NFLM2NonlinearModel(
        model_id=NFL_M2_NONLINEAR_MODEL_ID,
        feature_contract=NFL_M2_FEATURE_CONTRACT,
        basis_version=NFL_M2_NONLINEAR_BASIS_VERSION,
        base_feature_names=_base_names(),
        basis_feature_names=_basis_names(),
        base_means=tuple(map(float, means)),
        base_scales=tuple(map(float, scales)),
        margin_coefficients=tuple(map(float, margin_coef)),
        total_coefficients=tuple(map(float, total_coef)),
        residual_pairs=tuple((float(m), float(t)) for m, t in zip(margin_resid, total_resid)),
        train_seasons=seasons,
        ridge_alpha=alpha,
        margin_sigma=margin_sigma,
        total_sigma=total_sigma,
    )


def derive_nfl_m2_nonlinear_distribution(
    model: NFLM2NonlinearModel,
    row: dict[str, Any],
) -> tuple[dict[str, int], ...]:
    if model.model_id != NFL_M2_NONLINEAR_MODEL_ID or model.feature_contract != NFL_M2_FEATURE_CONTRACT:
        raise NFLM2NonlinearCandidateError("MODEL_IDENTITY_INVALID")
    if not model.residual_pairs:
        raise NFLM2NonlinearCandidateError("RESIDUAL_DISTRIBUTION_MISSING")
    margin_mu, total_mu = model.predict(row)
    return tuple(
        _reconcile_scores(margin_mu + margin_resid, total_mu + total_resid)
        for margin_resid, total_resid in model.residual_pairs
    )


def price_candidate_game_markets(distribution, *, spread_line: float, total_line: float):
    return price_nfl_m2_game_markets(distribution, spread_line=spread_line, total_line=total_line)
