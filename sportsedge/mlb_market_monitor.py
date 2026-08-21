from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable, Mapping


class MLBMarketMonitorError(ValueError):
    pass


def _finite(value: Any, field: str, *, lo: float | None = None, hi: float | None = None) -> float:
    if isinstance(value, bool):
        raise MLBMarketMonitorError(f"{field} must be numeric")
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise MLBMarketMonitorError(f"{field} must be numeric") from exc
    if not math.isfinite(x):
        raise MLBMarketMonitorError(f"{field} must be finite")
    if lo is not None and x < lo:
        raise MLBMarketMonitorError(f"{field} below minimum")
    if hi is not None and x > hi:
        raise MLBMarketMonitorError(f"{field} above maximum")
    return x


def _brier(p: float, y: float) -> float:
    return (p - y) ** 2


def _logloss(p: float, y: float) -> float:
    q = min(1 - 1e-12, max(1e-12, p))
    return -(y * math.log(q) + (1 - y) * math.log(1 - q))


@dataclass(frozen=True)
class MarketWindowMetrics:
    market: str
    n: int
    brier: float
    logloss: float
    mean_model_probability: float
    outcome_rate: float
    mean_edge: float | None
    mean_clv_probability_delta: float | None


@dataclass(frozen=True)
class DriftAssessment:
    market: str
    recent_n: int
    prior_n: int
    recent_brier: float | None
    prior_brier: float | None
    recent_logloss: float | None
    prior_logloss: float | None
    brier_delta: float | None
    logloss_delta: float | None
    status: str
    reason: str


def market_metrics(rows: Iterable[Mapping[str, Any]], *, market: str | None = None) -> MarketWindowMetrics:
    selected: list[Mapping[str, Any]] = []
    requested = str(market or "").strip().upper()
    for row in rows:
        row_market = str(row.get("market") or "").strip().upper()
        if requested and row_market != requested:
            continue
        selected.append(row)
    if not selected:
        raise MLBMarketMonitorError("no rows for market metrics")

    probs: list[float] = []
    outcomes: list[float] = []
    edges: list[float] = []
    clv_deltas: list[float] = []
    resolved_market = requested or str(selected[0].get("market") or "UNKNOWN").strip().upper()

    for row in selected:
        p = _finite(row.get("model_probability"), "model_probability", lo=0, hi=1)
        y = _finite(row.get("outcome"), "outcome", lo=0, hi=1)
        probs.append(p)
        outcomes.append(y)
        if row.get("fair_market_probability") is not None:
            fair = _finite(row.get("fair_market_probability"), "fair_market_probability", lo=0, hi=1)
            edges.append(p - fair)
        if row.get("closing_fair_probability") is not None and row.get("fair_market_probability") is not None:
            close = _finite(row.get("closing_fair_probability"), "closing_fair_probability", lo=0, hi=1)
            open_fair = _finite(row.get("fair_market_probability"), "fair_market_probability", lo=0, hi=1)
            clv_deltas.append(close - open_fair)

    n = len(probs)
    return MarketWindowMetrics(
        market=resolved_market,
        n=n,
        brier=sum(_brier(p, y) for p, y in zip(probs, outcomes)) / n,
        logloss=sum(_logloss(p, y) for p, y in zip(probs, outcomes)) / n,
        mean_model_probability=sum(probs) / n,
        outcome_rate=sum(outcomes) / n,
        mean_edge=(sum(edges) / len(edges)) if edges else None,
        mean_clv_probability_delta=(sum(clv_deltas) / len(clv_deltas)) if clv_deltas else None,
    )


def assess_market_drift(
    rows: Iterable[Mapping[str, Any]],
    *,
    market: str,
    recent_n: int = 50,
    prior_n: int = 100,
    minimum_recent: int = 30,
    minimum_prior: int = 50,
    brier_tolerance: float = 0.010,
    logloss_tolerance: float = 0.020,
) -> DriftAssessment:
    if recent_n <= 0 or prior_n <= 0:
        raise MLBMarketMonitorError("window sizes must be positive")
    if minimum_recent <= 0 or minimum_prior <= 0:
        raise MLBMarketMonitorError("minimum samples must be positive")
    brier_tol = _finite(brier_tolerance, "brier_tolerance", lo=0)
    logloss_tol = _finite(logloss_tolerance, "logloss_tolerance", lo=0)

    requested = str(market or "").strip().upper()
    selected = [r for r in rows if str(r.get("market") or "").strip().upper() == requested]
    if not selected:
        return DriftAssessment(requested, 0, 0, None, None, None, None, None, None,
                               "INSUFFICIENT_EVIDENCE", "no rows")

    # Caller must supply point-in-time rows in chronological order. We intentionally
    # do not infer timestamps here because this module is a pure diagnostic layer.
    recent = selected[-recent_n:]
    prior_end = max(0, len(selected) - recent_n)
    prior_start = max(0, prior_end - prior_n)
    prior = selected[prior_start:prior_end]

    if len(recent) < minimum_recent or len(prior) < minimum_prior:
        return DriftAssessment(requested, len(recent), len(prior), None, None, None, None, None, None,
                               "INSUFFICIENT_EVIDENCE", "paired rolling windows below minimum sample")

    recent_metrics = market_metrics(recent, market=requested)
    prior_metrics = market_metrics(prior, market=requested)
    brier_delta = recent_metrics.brier - prior_metrics.brier
    logloss_delta = recent_metrics.logloss - prior_metrics.logloss

    if brier_delta > brier_tol and logloss_delta > logloss_tol:
        status = "QUARANTINE_RESEARCH"
        reason = "recent calibration deteriorated on both Brier and log loss"
    elif brier_delta > brier_tol or logloss_delta > logloss_tol:
        status = "WATCH_RETEST"
        reason = "recent calibration deteriorated on one proper-scoring metric"
    else:
        status = "KEEP_MONITORING"
        reason = "no material rolling-window calibration deterioration"

    return DriftAssessment(
        requested,
        recent_metrics.n,
        prior_metrics.n,
        recent_metrics.brier,
        prior_metrics.brier,
        recent_metrics.logloss,
        prior_metrics.logloss,
        brier_delta,
        logloss_delta,
        status,
        reason,
    )


def edge_bucket_report(rows: Iterable[Mapping[str, Any]], *, buckets: tuple[tuple[float, float], ...] = ((0,.02),(.02,.04),(.04,.07),(.07,1.0))) -> tuple[dict[str, Any], ...]:
    out: list[dict[str, Any]] = []
    materialized = list(rows)
    for lo, hi in buckets:
        bucket: list[Mapping[str, Any]] = []
        for row in materialized:
            if row.get("fair_market_probability") is None:
                continue
            p = _finite(row.get("model_probability"), "model_probability", lo=0, hi=1)
            fair = _finite(row.get("fair_market_probability"), "fair_market_probability", lo=0, hi=1)
            edge = p - fair
            if lo <= edge < hi:
                bucket.append(row)
        if bucket:
            probs = [_finite(r.get("model_probability"), "model_probability", lo=0, hi=1) for r in bucket]
            ys = [_finite(r.get("outcome"), "outcome", lo=0, hi=1) for r in bucket]
            out.append({
                "edge_range": [lo, hi],
                "n": len(bucket),
                "mean_model_probability": sum(probs)/len(probs),
                "outcome_rate": sum(ys)/len(ys),
                "brier": sum(_brier(p,y) for p,y in zip(probs,ys))/len(bucket),
                "logloss": sum(_logloss(p,y) for p,y in zip(probs,ys))/len(bucket),
            })
        else:
            out.append({"edge_range": [lo, hi], "n": 0})
    return tuple(out)
