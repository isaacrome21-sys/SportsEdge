"""Research-only cross-sport diagnostics for SportsEdge.

These functions measure predictive quality, calibration, ablation deltas and drift.
They have no Model_P, promotion, Truth Gate, staking, OFFICIAL, or registry authority.
"""
from __future__ import annotations

from math import exp, isfinite, log, sqrt
from typing import Iterable, Mapping

_EPS = 1e-12


def _finite(values: Iterable[float], name: str) -> list[float]:
    out = [float(v) for v in values]
    if not out or any(not isfinite(v) for v in out):
        raise ValueError(f"RESEARCH_DIAGNOSTIC_INVALID_{name.upper()}")
    return out


def regression_metrics(predicted: Iterable[float], observed: Iterable[float]) -> dict[str, float]:
    p = _finite(predicted, "predicted")
    y = _finite(observed, "observed")
    if len(p) != len(y):
        raise ValueError("RESEARCH_DIAGNOSTIC_LENGTH_MISMATCH")
    errors = [a - b for a, b in zip(p, y)]
    return {
        "n": float(len(p)),
        "rmse": sqrt(sum(e * e for e in errors) / len(errors)),
        "mae": sum(abs(e) for e in errors) / len(errors),
        "mean_error": sum(errors) / len(errors),
    }


def _logit(p: float) -> float:
    q = min(1.0 - 1e-9, max(1e-9, p))
    return log(q / (1.0 - q))


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = exp(-x)
        return 1.0 / (1.0 + z)
    z = exp(x)
    return z / (1.0 + z)


def _calibration_intercept_slope(probs: list[float], outcomes: list[float]) -> tuple[float, float]:
    # Newton fit: logit(E[y]) = intercept + slope * logit(model_p).
    xs = [_logit(p) for p in probs]
    a, b = 0.0, 1.0
    for _ in range(50):
        g0 = g1 = h00 = h01 = h11 = 0.0
        for x, y in zip(xs, outcomes):
            q = _sigmoid(a + b * x)
            w = max(_EPS, q * (1.0 - q))
            r = y - q
            g0 += r
            g1 += r * x
            h00 += w
            h01 += w * x
            h11 += w * x * x
        det = h00 * h11 - h01 * h01
        if abs(det) < 1e-12:
            break
        da = (g0 * h11 - g1 * h01) / det
        db = (g1 * h00 - g0 * h01) / det
        a += da
        b += db
        if max(abs(da), abs(db)) < 1e-9:
            break
    return a, b


def probability_metrics(probabilities: Iterable[float], outcomes: Iterable[float], *, bins: int = 10) -> dict[str, float]:
    p = _finite(probabilities, "probabilities")
    y = _finite(outcomes, "outcomes")
    if len(p) != len(y):
        raise ValueError("RESEARCH_DIAGNOSTIC_LENGTH_MISMATCH")
    if bins < 2:
        raise ValueError("RESEARCH_DIAGNOSTIC_BINS_INVALID")
    if any(v < 0.0 or v > 1.0 for v in p) or any(v not in (0.0, 1.0) for v in y):
        raise ValueError("RESEARCH_DIAGNOSTIC_PROBABILITY_DOMAIN")
    clipped = [min(1.0 - 1e-15, max(1e-15, v)) for v in p]
    n = len(p)
    brier = sum((a - b) ** 2 for a, b in zip(p, y)) / n
    log_loss = -sum(b * log(a) + (1.0 - b) * log(1.0 - a) for a, b in zip(clipped, y)) / n
    ece = 0.0
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        idx = [j for j, v in enumerate(p) if (lo <= v < hi) or (i == bins - 1 and v == 1.0)]
        if not idx:
            continue
        mean_p = sum(p[j] for j in idx) / len(idx)
        mean_y = sum(y[j] for j in idx) / len(idx)
        ece += (len(idx) / n) * abs(mean_p - mean_y)
    intercept, slope = _calibration_intercept_slope(p, y)
    return {
        "n": float(n),
        "brier": brier,
        "log_loss": log_loss,
        "ece": ece,
        "calibration_intercept": intercept,
        "calibration_slope": slope,
    }


def ablation_delta(full: Mapping[str, float], ablated: Mapping[str, float]) -> dict[str, float]:
    """Return ablated-minus-full deltas for common lower-is-better metrics.

    Positive delta means removing the feature family made the metric worse and the
    family added value on the evaluated research split. This is diagnostic only.
    """
    keys = ("rmse", "mae", "brier", "log_loss", "ece")
    out: dict[str, float] = {}
    for key in keys:
        if key in full and key in ablated:
            out[f"delta_{key}"] = float(ablated[key]) - float(full[key])
    if not out:
        raise ValueError("RESEARCH_DIAGNOSTIC_NO_COMPARABLE_METRICS")
    return out


def population_stability_index(reference: Iterable[float], current: Iterable[float], *, bins: int = 10) -> float:
    """PSI using reference quantile cut points; intended for shadow drift monitoring."""
    ref = sorted(_finite(reference, "reference"))
    cur = _finite(current, "current")
    if bins < 2 or len(ref) < bins:
        raise ValueError("RESEARCH_DIAGNOSTIC_PSI_BINS_INVALID")
    cuts = []
    for i in range(1, bins):
        pos = min(len(ref) - 1, max(0, int(i * len(ref) / bins)))
        cuts.append(ref[pos])

    def bucket(v: float) -> int:
        for i, cut in enumerate(cuts):
            if v < cut:
                return i
        return len(cuts)

    ref_counts = [0] * bins
    cur_counts = [0] * bins
    for v in ref:
        ref_counts[bucket(v)] += 1
    for v in cur:
        cur_counts[bucket(v)] += 1
    psi = 0.0
    for r, c in zip(ref_counts, cur_counts):
        rp = max(_EPS, r / len(ref))
        cp = max(_EPS, c / len(cur))
        psi += (cp - rp) * log(cp / rp)
    return psi
