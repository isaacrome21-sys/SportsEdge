"""Research-only overdispersed count challenger for sportsbook prop thresholds.

The production generic count engine remains unchanged. This module supplies a
price-independent Poisson-vs-negative-binomial challenger whose distribution shape
is estimated only from strictly-prior realized counts. Promotion is per-market and
requires the cross-sport historical research gates.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from hashlib import sha256
import json
from math import exp, floor, isfinite, lgamma, log
from statistics import fmean
from typing import Any, Iterable


COUNT_DISTRIBUTION_CANDIDATE_VERSION = "count_nb_moments_shrunk_v1_candidate"


class CountDistributionCandidateError(ValueError):
    pass


def _count(value: Any) -> float:
    if isinstance(value, bool):
        raise CountDistributionCandidateError("COUNT_NUMERIC_REQUIRED")
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise CountDistributionCandidateError("COUNT_NUMERIC_REQUIRED") from exc
    if not isfinite(x) or x < 0 or abs(x - round(x)) > 1e-9:
        raise CountDistributionCandidateError("COUNT_NONNEGATIVE_INTEGER_REQUIRED")
    return float(round(x))


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise CountDistributionCandidateError(f"{field}:NUMERIC_REQUIRED")
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise CountDistributionCandidateError(f"{field}:NUMERIC_REQUIRED") from exc
    if not isfinite(x):
        raise CountDistributionCandidateError(f"{field}:NONFINITE")
    return x


@dataclass(frozen=True)
class CountDistributionFit:
    version: str
    n_history: int
    mean: float
    raw_variance: float
    shrunk_variance: float
    distribution: str
    dispersion_r: float | None
    shrinkage_games: float
    fit_sha256: str


def fit_count_distribution(
    prior_counts: Iterable[Any], *,
    shrinkage_games: float = 20.0,
    min_history: int = 10,
) -> CountDistributionFit:
    values = [_count(value) for value in prior_counts]
    if len(values) < int(min_history):
        raise CountDistributionCandidateError(
            f"COUNT_HISTORY_INSUFFICIENT:{len(values)}<{int(min_history)}"
        )
    strength = _finite(shrinkage_games, "shrinkage_games")
    if strength < 0:
        raise CountDistributionCandidateError("SHRINKAGE_GAMES_NEGATIVE")
    mu = float(fmean(values))
    if len(values) <= 1:
        raw_var = mu
    else:
        raw_var = sum((x - mu) ** 2 for x in values) / (len(values) - 1)
    # Shrink sample variance toward the Poisson variance (mean). This prevents a
    # tiny chronological sample from creating an extreme negative-binomial tail.
    weight = len(values) / (len(values) + strength) if strength > 0 else 1.0
    shrunk_var = weight * raw_var + (1.0 - weight) * mu

    distribution = "POISSON"
    r: float | None = None
    if mu > 0 and shrunk_var > mu + 1e-12:
        r = (mu * mu) / (shrunk_var - mu)
        if isfinite(r) and r > 0:
            distribution = "NEGATIVE_BINOMIAL"
        else:
            r = None

    raw = {
        "version": COUNT_DISTRIBUTION_CANDIDATE_VERSION,
        "n_history": len(values),
        "mean": mu,
        "raw_variance": raw_var,
        "shrunk_variance": shrunk_var,
        "distribution": distribution,
        "dispersion_r": r,
        "shrinkage_games": strength,
        "prior_counts": values,
    }
    digest = sha256(json.dumps(raw, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return CountDistributionFit(
        version=COUNT_DISTRIBUTION_CANDIDATE_VERSION,
        n_history=len(values),
        mean=mu,
        raw_variance=raw_var,
        shrunk_variance=shrunk_var,
        distribution=distribution,
        dispersion_r=r,
        shrinkage_games=strength,
        fit_sha256=digest,
    )


def _poisson_pmf(k: int, mu: float) -> float:
    if mu <= 0:
        return 1.0 if k == 0 else 0.0
    return exp(-mu + k * log(mu) - lgamma(k + 1.0))


def _nb_pmf(k: int, mu: float, r: float) -> float:
    if mu <= 0:
        return 1.0 if k == 0 else 0.0
    p = r / (r + mu)
    return exp(
        lgamma(k + r) - lgamma(r) - lgamma(k + 1.0)
        + r * log(p) + k * log(1.0 - p)
    )


def _cdf(k: int, fit: CountDistributionFit) -> float:
    if k < 0:
        return 0.0
    if fit.mean <= 0:
        return 1.0
    total = 0.0
    for x in range(k + 1):
        if fit.distribution == "NEGATIVE_BINOMIAL":
            if fit.dispersion_r is None:
                raise CountDistributionCandidateError("NB_DISPERSION_MISSING")
            total += _nb_pmf(x, fit.mean, fit.dispersion_r)
        else:
            total += _poisson_pmf(x, fit.mean)
    return min(1.0, max(0.0, total))


def price_count_threshold(
    fit: CountDistributionFit, *,
    line: Any,
) -> dict[str, Any]:
    threshold = _finite(line, "line")
    if threshold < 0:
        raise CountDistributionCandidateError("LINE_NEGATIVE")
    k = floor(threshold)
    integer_line = abs(threshold - round(threshold)) < 1e-12
    p_over = 1.0 - _cdf(k, fit)
    if integer_line:
        target = int(round(threshold))
        p_under = _cdf(target - 1, fit)
        p_push = _cdf(target, fit) - p_under
    else:
        p_under = 1.0 - p_over
        p_push = 0.0
    total = p_over + p_under + p_push
    if abs(total - 1.0) > 1e-9:
        raise CountDistributionCandidateError("COUNT_PROBABILITY_MASS_INVALID")
    readout = {
        "version": COUNT_DISTRIBUTION_CANDIDATE_VERSION,
        "fit_sha256": fit.fit_sha256,
        "line": threshold,
        "over": p_over,
        "under": p_under,
        "push": p_push,
        "distribution": fit.distribution,
        "mean": fit.mean,
        "dispersion_r": fit.dispersion_r,
    }
    readout["readout_sha256"] = sha256(
        json.dumps(readout, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    return readout


def fit_payload(fit: CountDistributionFit) -> dict[str, Any]:
    return asdict(fit)
