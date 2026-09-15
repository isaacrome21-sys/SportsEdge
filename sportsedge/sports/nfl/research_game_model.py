"""Development/validation-only NFL game model research.

This module intentionally stops at research predictions/metrics. It has no production
Model_P, promotion, Truth Gate, pricing, staking, OFFICIAL, or prop authority.
"""
from __future__ import annotations

from math import isfinite
from typing import Iterable, Sequence


FEATURE_NAMES = (
    "lagged_epa_per_play",
    "lagged_pass_epa_per_play",
    "lagged_rush_epa_per_play",
    "lagged_success_rate",
    "lagged_explosive_play_rate",
    "lagged_early_down_pass_rate",
    "lagged_sack_rate_allowed",
    "lagged_turnover_rate",
    "lagged_qb_cpoe",
)


def game_vector(home: dict, away: dict, feature_names: Sequence[str] = FEATURE_NAMES) -> list[float]:
    """Home-minus-away feature vector; no market data accepted or inferred."""
    out = []
    for name in feature_names:
        if name not in home or name not in away:
            raise ValueError(f"NFL_RESEARCH_FEATURE_MISSING:{name}")
        h = float(home[name])
        a = float(away[name])
        if not isfinite(h) or not isfinite(a):
            raise ValueError(f"NFL_RESEARCH_FEATURE_NONFINITE:{name}")
        out.append(h - a)
    return out


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Small deterministic Gauss-Jordan solver with partial pivoting."""
    n = len(b)
    aug = [list(a[i]) + [float(b[i])] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) < 1e-12:
            raise ValueError("NFL_RESEARCH_SINGULAR_SYSTEM")
        aug[col], aug[pivot] = aug[pivot], aug[col]
        scale = aug[col][col]
        aug[col] = [v / scale for v in aug[col]]
        for row in range(n):
            if row == col:
                continue
            factor = aug[row][col]
            if factor == 0.0:
                continue
            aug[row] = [x - factor * y for x, y in zip(aug[row], aug[col])]
    return [aug[i][-1] for i in range(n)]


def fit_ridge(x: Iterable[Sequence[float]], y: Iterable[float], *, alpha: float = 1.0) -> list[float]:
    rows = [list(map(float, row)) for row in x]
    targets = [float(v) for v in y]
    if not rows or len(rows) != len(targets):
        raise ValueError("NFL_RESEARCH_FIT_ROWS_INVALID")
    width = len(rows[0])
    if width == 0 or any(len(row) != width for row in rows):
        raise ValueError("NFL_RESEARCH_FIT_WIDTH_INVALID")
    if alpha < 0:
        raise ValueError("NFL_RESEARCH_ALPHA_INVALID")
    # Intercept is column 0 and is not penalized.
    design = [[1.0] + row for row in rows]
    p = width + 1
    gram = [[0.0] * p for _ in range(p)]
    rhs = [0.0] * p
    for row, target in zip(design, targets):
        for i in range(p):
            rhs[i] += row[i] * target
            for j in range(p):
                gram[i][j] += row[i] * row[j]
    for i in range(1, p):
        gram[i][i] += alpha
    return _solve(gram, rhs)


def predict_ridge(coefficients: Sequence[float], x: Iterable[Sequence[float]]) -> list[float]:
    coef = list(map(float, coefficients))
    if len(coef) < 1:
        raise ValueError("NFL_RESEARCH_COEFFICIENTS_INVALID")
    out = []
    for row in x:
        values = list(map(float, row))
        if len(values) + 1 != len(coef):
            raise ValueError("NFL_RESEARCH_PREDICT_WIDTH_MISMATCH")
        out.append(coef[0] + sum(c * v for c, v in zip(coef[1:], values)))
    return out
