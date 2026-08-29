"""Paired chronological comparison helpers for CFB model replacement.

Candidate and baseline must be scored on identical held-out rows. Confidence bounds are
computed with a deterministic paired bootstrap stratified by outer season so changing
model names or row order cannot change the inference.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite, log
from typing import Any, Iterable, Mapping

import numpy as np


class CFBModelComparisonError(ValueError):
    pass


def _p(value: Any, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise CFBModelComparisonError(f"{field}:NUMERIC_REQUIRED") from exc
    if not isfinite(out) or not 0.0 <= out <= 1.0:
        raise CFBModelComparisonError(f"{field}:PROBABILITY_RANGE")
    return out


def _y(value: Any) -> int:
    if value in (0, 0.0, False):
        return 0
    if value in (1, 1.0, True):
        return 1
    raise CFBModelComparisonError("OUTCOME_BINARY_REQUIRED")


def _clip(p: float) -> float:
    return min(1.0 - 1e-12, max(1e-12, float(p)))


def _brier_loss(p: float, y: int) -> float:
    return (float(p) - int(y)) ** 2


def _logloss(p: float, y: int) -> float:
    value = _clip(p)
    return -(y * log(value) + (1 - y) * log(1.0 - value))


@dataclass(frozen=True)
class PairedMetricDelta:
    metric: str
    n: int
    seasons: tuple[int, ...]
    baseline_mean: float
    candidate_mean: float
    mean_delta: float
    upper_95: float
    bootstrap_resamples: int
    bootstrap_seed: int
    quantile_method: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def paired_stratified_bootstrap_delta(
    rows: Iterable[Mapping[str, Any]],
    *,
    metric: str,
    baseline_prob_key: str = "baseline_prob",
    candidate_prob_key: str = "candidate_prob",
    outcome_key: str = "outcome",
    season_key: str = "season",
    resamples: int = 10000,
    seed: int = 20260829,
    upper_quantile: float = 0.95,
    quantile_method: str = "linear",
) -> PairedMetricDelta:
    data = [dict(row) for row in rows]
    if len(data) < 2:
        raise CFBModelComparisonError("PAIRED_COMPARISON_ROWS_INSUFFICIENT")
    name = str(metric).strip().upper()
    if name not in {"BRIER", "LOGLOSS"}:
        raise CFBModelComparisonError("PAIRED_COMPARISON_METRIC_INVALID")
    if isinstance(resamples, bool) or int(resamples) < 100:
        raise CFBModelComparisonError("BOOTSTRAP_RESAMPLES_INSUFFICIENT")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise CFBModelComparisonError("BOOTSTRAP_SEED_INTEGER_REQUIRED")
    if not 0.5 < float(upper_quantile) < 1.0:
        raise CFBModelComparisonError("BOOTSTRAP_QUANTILE_INVALID")
    if quantile_method != "linear":
        raise CFBModelComparisonError("BOOTSTRAP_QUANTILE_METHOD_UNSUPPORTED")

    grouped: dict[int, list[tuple[float, float]]] = {}
    baseline_losses: list[float] = []
    candidate_losses: list[float] = []
    for row in data:
        season = int(row[season_key])
        outcome = _y(row[outcome_key])
        baseline_p = _p(row[baseline_prob_key], baseline_prob_key)
        candidate_p = _p(row[candidate_prob_key], candidate_prob_key)
        loss = _brier_loss if name == "BRIER" else _logloss
        baseline_loss = float(loss(baseline_p, outcome))
        candidate_loss = float(loss(candidate_p, outcome))
        grouped.setdefault(season, []).append((baseline_loss, candidate_loss))
        baseline_losses.append(baseline_loss)
        candidate_losses.append(candidate_loss)

    seasons = tuple(sorted(grouped))
    if len(seasons) < 2:
        raise CFBModelComparisonError("BOOTSTRAP_MULTISEASON_REQUIRED")
    rng = np.random.default_rng(seed)
    deltas = np.empty(int(resamples), dtype=float)
    for draw in range(int(resamples)):
        baseline_total = 0.0
        candidate_total = 0.0
        count = 0
        for season in seasons:
            values = grouped[season]
            idx = rng.integers(0, len(values), size=len(values))
            for i in idx.tolist():
                baseline_loss, candidate_loss = values[i]
                baseline_total += baseline_loss
                candidate_total += candidate_loss
                count += 1
        deltas[draw] = (candidate_total - baseline_total) / count

    baseline_mean = float(np.mean(np.asarray(baseline_losses, dtype=float)))
    candidate_mean = float(np.mean(np.asarray(candidate_losses, dtype=float)))
    upper = float(np.quantile(deltas, float(upper_quantile), method=quantile_method))
    return PairedMetricDelta(
        metric=name,
        n=len(data),
        seasons=seasons,
        baseline_mean=baseline_mean,
        candidate_mean=candidate_mean,
        mean_delta=candidate_mean - baseline_mean,
        upper_95=upper,
        bootstrap_resamples=int(resamples),
        bootstrap_seed=int(seed),
        quantile_method=quantile_method,
    )
