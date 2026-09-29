"""Deterministic discrete kernel pricing for low-sample MLB count markets.

The helper turns a finite set of strictly-prior integer outcomes into a proper
predictive PMF. It is intentionally price-independent and standard-library only.
It does not claim empirical calibration; downstream validation gates still decide
whether a market is eligible for promotion.
"""
from __future__ import annotations

from math import ceil, exp, isfinite, sqrt
from typing import Sequence


class CountKernelError(ValueError):
    pass


def normalize_weights(raw: Sequence[float] | None, n: int) -> list[float]:
    if n <= 0:
        raise CountKernelError("positive sample required")
    if raw is None:
        return [1.0 / n] * n
    if len(raw) != n:
        raise CountKernelError("weights must align with values")
    vals = [float(v) for v in raw]
    if any((not isfinite(v)) or v <= 0 for v in vals):
        raise CountKernelError("weights must be finite and strictly positive")
    total = sum(vals)
    return [v / total for v in vals]


def effective_sample_size(weights: Sequence[float]) -> float:
    denom = sum(float(w) ** 2 for w in weights)
    if not isfinite(denom) or denom <= 0:
        raise CountKernelError("invalid normalized weights")
    return 1.0 / denom


def discrete_kernel_pmf(
    values: Sequence[int],
    *,
    weights: Sequence[float] | None = None,
    lower: int = 0,
    upper: int | None = None,
    target_mean: float | None = None,
) -> tuple[dict[int, float], dict[str, float]]:
    """Return a normalized integer PMF plus auditable smoothing metadata.

    Historical rows remain the centers of the distribution. A Gaussian kernel
    supplies finite predictive tail mass rather than declaring an unseen outcome
    impossible. ``target_mean`` may shift all centers together when a separately
    built, price-independent context model supplies a mean target.
    """
    if not values:
        raise CountKernelError("values required")
    if any(type(v) is not int for v in values):
        raise CountKernelError("values must be integers")
    if type(lower) is not int or (upper is not None and type(upper) is not int):
        raise CountKernelError("support bounds must be integers")
    if upper is not None and upper < lower:
        raise CountKernelError("invalid support bounds")

    ws = normalize_weights(weights, len(values))
    raw_mean = sum(w * v for v, w in zip(values, ws))
    mean_target = raw_mean if target_mean is None else float(target_mean)
    if not isfinite(mean_target) or mean_target < lower:
        raise CountKernelError("target_mean invalid")
    if upper is not None:
        mean_target = min(float(upper), mean_target)

    shift = mean_target - raw_mean
    centers = [max(float(lower), float(v) + shift) for v in values]
    if upper is not None:
        centers = [min(float(upper), c) for c in centers]

    center_mean = sum(w * c for c, w in zip(centers, ws))
    variance = sum(w * (c - center_mean) ** 2 for c, w in zip(centers, ws))
    n_eff = effective_sample_size(ws)

    # An observed 10-for-10 history is evidence of a high rate, not proof of a
    # 100% event. The mean-dependent floor also keeps high-count degenerate
    # samples from collapsing numerically to a point mass.
    bandwidth = max(
        0.35,
        0.20 * sqrt(max(center_mean, 0.0) + 1.0),
        1.06 * sqrt(max(variance, 0.25)) * n_eff ** (-0.2),
    )

    if upper is None:
        upper = max(
            lower + 1,
            int(ceil(max(centers) + 6.0 * bandwidth)),
            int(ceil(center_mean + 8.0 * sqrt(max(center_mean, 0.0) + 1.0))),
            max(values) + 4,
        )
        upper = min(200, upper)

    masses: dict[int, float] = {}
    for k in range(lower, upper + 1):
        masses[k] = sum(
            w * exp(-0.5 * ((float(k) - center) / bandwidth) ** 2)
            for center, w in zip(centers, ws)
        )
    total = sum(masses.values())
    if not isfinite(total) or total <= 0:
        raise CountKernelError("kernel mass invalid")
    pmf = {k: mass / total for k, mass in masses.items()}
    return pmf, {
        "raw_mean": float(raw_mean),
        "target_mean": float(mean_target),
        "predictive_mean": float(sum(k * p for k, p in pmf.items())),
        "bandwidth": float(bandwidth),
        "effective_sample_size": float(n_eff),
        "support_lower": float(lower),
        "support_upper": float(upper),
    }


def price_from_pmf(pmf: dict[int, float], *, line: float, side: str) -> tuple[float, float]:
    if not isfinite(float(line)) or float(line) < 0:
        raise CountKernelError("line invalid")
    side = str(side).upper()
    if side not in {"OVER", "UNDER"}:
        raise CountKernelError("side must be OVER or UNDER")
    line = float(line)
    p_over = sum(p for value, p in pmf.items() if value > line)
    p_under = sum(p for value, p in pmf.items() if value < line)
    p_push = sum(p for value, p in pmf.items() if value == line) if line.is_integer() else 0.0
    if abs(p_over + p_under + p_push - 1.0) > 1e-10:
        raise CountKernelError("probability mass does not conserve")
    return (p_over if side == "OVER" else p_under), p_push
