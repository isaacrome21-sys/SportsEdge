"""Proper scoring metrics for probability forecasts. Pure functions.

Records are dicts: {"model_p": float in [0, 1], "outcome": 0.0 | 0.5 | 1.0}.
An outcome of 0.5 represents a push (graded half-win, half-loss).

Research only.
"""
from __future__ import annotations

import math


class MetricError(ValueError):
    pass


def _checked(records):
    if not isinstance(records, list) or not records:
        raise MetricError("BACKTEST_METRICS_NO_RECORDS")
    out = []
    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            raise MetricError("BACKTEST_METRIC_RECORD_NOT_OBJECT")
        try:
            p = float(rec["model_p"])
            y = float(rec["outcome"])
        except (KeyError, ValueError, TypeError) as exc:
            raise MetricError("BACKTEST_METRIC_RECORD_MALFORMED") from exc
        if not (0.0 <= p <= 1.0) or not math.isfinite(p):
            raise MetricError("BACKTEST_METRIC_PROBABILITY_INVALID")
        if y not in (0.0, 0.5, 1.0):
            raise MetricError("BACKTEST_METRIC_OUTCOME_INVALID")
        out.append((p, y))
    return out


def brier_score(records):
    """Mean squared error of probability forecasts. Lower is better."""
    return sum((p - y) ** 2 for p, y in _checked(records)) / len(records)


def log_loss(records):
    """Mean negative log-likelihood (natural log). Lower is better.

    Fail-closed on degenerate p=0/1: a model emitting absolute certainty is
    overconfident and must be fixed upstream, not silently clipped.
    """
    total = 0.0
    for p, y in _checked(records):
        if p <= 0.0 or p >= 1.0:
            raise MetricError("BACKTEST_LOG_LOSS_DEGENERATE_PROBABILITY")
        total += -(y * math.log(p) + (1.0 - y) * math.log(1.0 - p))
    return total / len(records)


def calibration_bins(records, n_bins=10):
    """Reliability table: equal-width bins over [0, 1].

    Each bin: {bin, lo, hi, n, mean_p, hit_rate}. Empty bins report
    mean_p/hit_rate as None rather than inventing values.
    """
    if not isinstance(n_bins, int) or n_bins < 2:
        raise MetricError("BACKTEST_METRIC_BINS_INVALID")
    checked = _checked(records)
    bins = []
    for b in range(n_bins):
        lo, hi = b / n_bins, (b + 1) / n_bins
        ps = [p for p, _ in checked if (lo <= p < hi) or (b == n_bins - 1 and p == 1.0)]
        ys = [y for p, y in checked if (lo <= p < hi) or (b == n_bins - 1 and p == 1.0)]
        bins.append({
            "bin": b,
            "lo": round(lo, 4),
            "hi": round(hi, 4),
            "n": len(ps),
            "mean_p": (sum(ps) / len(ps)) if ps else None,
            "hit_rate": (sum(ys) / len(ys)) if ys else None,
        })
    return bins


def hit_rate_at_thresholds(records, thresholds):
    """For each threshold t: among predictions with model_p >= t, the
    fraction with outcome 1.0 (pushes count as 0.5)."""
    checked = _checked(records)
    out = []
    for t in thresholds:
        try:
            thr = float(t)
        except (ValueError, TypeError) as exc:
            raise MetricError("BACKTEST_METRIC_THRESHOLD_INVALID") from exc
        if not 0.0 <= thr <= 1.0:
            raise MetricError("BACKTEST_METRIC_THRESHOLD_INVALID")
        sel = [(p, y) for p, y in checked if p >= thr]
        out.append({
            "threshold": thr,
            "n": len(sel),
            "hit_rate": (sum(y for _, y in sel) / len(sel)) if sel else None,
        })
    return out


def summarize(records):
    """One-dict summary: n, brier, log_loss, mean_p, base_rate."""
    checked = _checked(records)
    n = len(checked)
    return {
        "n": n,
        "brier": brier_score(records),
        "log_loss": log_loss(records),
        "mean_p": sum(p for p, _ in checked) / n,
        "base_rate": sum(y for _, y in checked) / n,
    }
