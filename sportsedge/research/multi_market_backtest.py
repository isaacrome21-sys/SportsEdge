"""Cross-sport, market-agnostic historical research evaluation.

This module is deliberately separated from production promotion. It evaluates
already-produced, point-in-time prediction rows and never mutates Truth Gate
eligibility or edge floors.

Canonical binary row fields:
    sport, market, event_id, season
    event_start_ts, decision_ts, feature_asof_ts
    outcome: 1, 0, or None for push/void
    model_p
Optional:
    benchmark_p       contemporaneous no-vig or frozen incumbent probability
    offered_decimal   exact offered price for the modeled side
    clv_pct            canonical market-specific CLV value in percentage points
    selected           whether the frozen decision policy bet the row

All timestamps must be timezone-aware and satisfy:
    feature_asof_ts <= decision_ts < event_start_ts
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import exp, isfinite, log
from random import Random
from statistics import mean
from typing import Any, Callable, Iterable, Mapping, Sequence


class ResearchBacktestError(ValueError):
    pass


EPS = 1e-9


def _dt(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise ResearchBacktestError(f"{field}:INVALID_TIMESTAMP") from exc
    if dt.tzinfo is None:
        raise ResearchBacktestError(f"{field}:NAIVE_TIMESTAMP")
    return dt


def _prob(value: Any, field: str) -> float:
    try:
        p = float(value)
    except (TypeError, ValueError) as exc:
        raise ResearchBacktestError(f"{field}:PROBABILITY_REQUIRED") from exc
    if not isfinite(p) or not 0.0 < p < 1.0:
        raise ResearchBacktestError(f"{field}:PROBABILITY_OUT_OF_RANGE")
    return p


def _finite(value: Any, field: str) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise ResearchBacktestError(f"{field}:NUMERIC_REQUIRED") from exc
    if not isfinite(x):
        raise ResearchBacktestError(f"{field}:NONFINITE")
    return x


def _outcome(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    try:
        x = int(value)
    except (TypeError, ValueError) as exc:
        raise ResearchBacktestError("outcome:BINARY_OR_NULL_REQUIRED") from exc
    if x not in (0, 1):
        raise ResearchBacktestError("outcome:BINARY_OR_NULL_REQUIRED")
    return x


@dataclass(frozen=True)
class BinaryResearchRow:
    sport: str
    market: str
    event_id: str
    season: int
    event_start_ts: datetime
    decision_ts: datetime
    feature_asof_ts: datetime
    outcome: int | None
    model_p: float
    benchmark_p: float | None = None
    offered_decimal: float | None = None
    clv_pct: float | None = None
    selected: bool = True

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "BinaryResearchRow":
        sport = str(row.get("sport") or "").strip().upper()
        market = str(row.get("market") or "").strip().upper()
        event_id = str(row.get("event_id") or row.get("game_id") or "").strip()
        if not sport or not market or not event_id:
            raise ResearchBacktestError("IDENTITY_REQUIRED")
        try:
            season = int(row["season"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ResearchBacktestError("season:INTEGER_REQUIRED") from exc
        event_start = _dt(row.get("event_start_ts"), "event_start_ts")
        decision = _dt(row.get("decision_ts"), "decision_ts")
        feature_asof = _dt(row.get("feature_asof_ts"), "feature_asof_ts")
        if not feature_asof <= decision:
            raise ResearchBacktestError("FEATURE_AFTER_DECISION")
        if not decision < event_start:
            raise ResearchBacktestError("DECISION_NOT_BEFORE_EVENT")
        benchmark_raw = row.get("benchmark_p")
        benchmark = None if benchmark_raw in (None, "") else _prob(benchmark_raw, "benchmark_p")
        offered_raw = row.get("offered_decimal")
        offered = None
        if offered_raw not in (None, ""):
            offered = _finite(offered_raw, "offered_decimal")
            if offered <= 1.0:
                raise ResearchBacktestError("offered_decimal:MUST_EXCEED_ONE")
        clv_raw = row.get("clv_pct")
        clv = None if clv_raw in (None, "") else _finite(clv_raw, "clv_pct")
        selected_raw = row.get("selected", True)
        if type(selected_raw) is not bool:
            raise ResearchBacktestError("selected:BOOLEAN_REQUIRED")
        return cls(
            sport=sport,
            market=market,
            event_id=event_id,
            season=season,
            event_start_ts=event_start,
            decision_ts=decision,
            feature_asof_ts=feature_asof,
            outcome=_outcome(row.get("outcome")),
            model_p=_prob(row.get("model_p"), "model_p"),
            benchmark_p=benchmark,
            offered_decimal=offered,
            clv_pct=clv,
            selected=selected_raw,
        )


def canonicalize_rows(rows: Iterable[Mapping[str, Any] | BinaryResearchRow]) -> tuple[BinaryResearchRow, ...]:
    out = tuple(row if isinstance(row, BinaryResearchRow) else BinaryResearchRow.from_mapping(row) for row in rows)
    if not out:
        raise ResearchBacktestError("EMPTY_RESEARCH_ROWS")
    identities = {(r.sport, r.market) for r in out}
    if len(identities) != 1:
        raise ResearchBacktestError("MIXED_SPORT_OR_MARKET")
    ordered = tuple(sorted(out, key=lambda r: (r.event_start_ts, r.event_id, r.decision_ts)))
    seen: set[tuple[str, datetime]] = set()
    for row in ordered:
        key = (row.event_id, row.decision_ts)
        if key in seen:
            raise ResearchBacktestError("DUPLICATE_EVENT_DECISION_IDENTITY")
        seen.add(key)
    return ordered


def brier_score(rows: Sequence[BinaryResearchRow], *, probability: Callable[[BinaryResearchRow], float | None]) -> float:
    pairs = [(r.outcome, probability(r)) for r in rows if r.outcome in (0, 1)]
    pairs = [(int(y), float(p)) for y, p in pairs if p is not None]
    if not pairs:
        raise ResearchBacktestError("NO_BINARY_ROWS_FOR_BRIER")
    return mean((p - y) ** 2 for y, p in pairs)


def log_loss(rows: Sequence[BinaryResearchRow], *, probability: Callable[[BinaryResearchRow], float | None]) -> float:
    pairs = [(r.outcome, probability(r)) for r in rows if r.outcome in (0, 1)]
    pairs = [(int(y), min(1.0 - EPS, max(EPS, float(p)))) for y, p in pairs if p is not None]
    if not pairs:
        raise ResearchBacktestError("NO_BINARY_ROWS_FOR_LOG_LOSS")
    return mean(-(y * log(p) + (1 - y) * log(1.0 - p)) for y, p in pairs)


def expected_calibration_error(rows: Sequence[BinaryResearchRow], *, bins: int = 10) -> float:
    if bins < 2:
        raise ResearchBacktestError("ECE_BINS_INVALID")
    pairs = sorted((r.model_p, int(r.outcome)) for r in rows if r.outcome in (0, 1))
    if not pairs:
        raise ResearchBacktestError("NO_BINARY_ROWS_FOR_ECE")
    n = len(pairs)
    weighted = 0.0
    for i in range(bins):
        lo = (i * n) // bins
        hi = ((i + 1) * n) // bins
        bucket = pairs[lo:hi]
        if not bucket:
            continue
        avg_p = mean(p for p, _ in bucket)
        avg_y = mean(y for _, y in bucket)
        weighted += (len(bucket) / n) * abs(avg_p - avg_y)
    return weighted


def calibration_intercept_slope(rows: Sequence[BinaryResearchRow], *, max_iter: int = 50) -> tuple[float, float]:
    """Logistic recalibration y ~ intercept + slope * logit(model_p)."""
    pairs = [(r.model_p, int(r.outcome)) for r in rows if r.outcome in (0, 1)]
    if len(pairs) < 20:
        raise ResearchBacktestError("CALIBRATION_ROWS_INSUFFICIENT")
    xs = [log(p / (1.0 - p)) for p, _ in pairs]
    ys = [y for _, y in pairs]
    a, b = 0.0, 1.0
    ridge = 1e-9
    for _ in range(max_iter):
        g0 = g1 = 0.0
        h00 = h01 = h11 = 0.0
        for x, y in zip(xs, ys):
            z = max(-35.0, min(35.0, a + b * x))
            q = 1.0 / (1.0 + exp(-z))
            w = max(EPS, q * (1.0 - q))
            diff = y - q
            g0 += diff
            g1 += diff * x
            h00 += w
            h01 += w * x
            h11 += w * x * x
        h00 += ridge
        h11 += ridge
        det = h00 * h11 - h01 * h01
        if abs(det) < 1e-15:
            raise ResearchBacktestError("CALIBRATION_HESSIAN_SINGULAR")
        da = (g0 * h11 - g1 * h01) / det
        db = (g1 * h00 - g0 * h01) / det
        a += da
        b += db
        if max(abs(da), abs(db)) < 1e-9:
            break
    if not isfinite(a) or not isfinite(b):
        raise ResearchBacktestError("CALIBRATION_FIT_NONFINITE")
    return a, b


def unit_roi(rows: Sequence[BinaryResearchRow]) -> dict[str, float | int | None]:
    priced = [r for r in rows if r.selected and r.offered_decimal is not None and r.outcome in (0, 1, None)]
    if not priced:
        return {"n": 0, "roi": None, "profit_units": None, "max_drawdown_units": None}
    pnl: list[float] = []
    for row in priced:
        if row.outcome is None:
            pnl.append(0.0)
        elif row.outcome == 1:
            pnl.append(float(row.offered_decimal) - 1.0)
        else:
            pnl.append(-1.0)
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in pnl:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    total = sum(pnl)
    return {
        "n": len(priced),
        "roi": total / len(priced),
        "profit_units": total,
        "max_drawdown_units": max_drawdown,
    }


def _mean_optional(values: Iterable[float | None]) -> float | None:
    clean = [float(x) for x in values if x is not None]
    return mean(clean) if clean else None


def summarize_binary_market(rows: Iterable[Mapping[str, Any] | BinaryResearchRow], *, bins: int = 10) -> dict[str, Any]:
    data = canonicalize_rows(rows)
    binary_n = sum(r.outcome in (0, 1) for r in data)
    pushes = sum(r.outcome is None for r in data)
    intercept = slope = None
    if binary_n >= 20:
        intercept, slope = calibration_intercept_slope(data)
    benchmark_rows = [r for r in data if r.outcome in (0, 1) and r.benchmark_p is not None]
    roi = unit_roi(data)
    return {
        "sport": data[0].sport,
        "market": data[0].market,
        "n_rows": len(data),
        "n_binary": binary_n,
        "n_push_or_void": pushes,
        "seasons": sorted({r.season for r in data}),
        "model_brier": brier_score(data, probability=lambda r: r.model_p),
        "model_log_loss": log_loss(data, probability=lambda r: r.model_p),
        "ece": expected_calibration_error(data, bins=bins),
        "calibration_intercept": intercept,
        "calibration_slope": slope,
        "benchmark_n": len(benchmark_rows),
        "benchmark_brier": (
            brier_score(benchmark_rows, probability=lambda r: r.benchmark_p) if benchmark_rows else None
        ),
        "benchmark_log_loss": (
            log_loss(benchmark_rows, probability=lambda r: r.benchmark_p) if benchmark_rows else None
        ),
        "avg_model_minus_benchmark_p": _mean_optional(
            r.model_p - r.benchmark_p for r in benchmark_rows if r.benchmark_p is not None
        ),
        "avg_clv_pct": _mean_optional(r.clv_pct for r in data if r.selected),
        **{f"bet_{k}": v for k, v in roi.items()},
    }


def _cluster_bootstrap_samples(
    rows: Sequence[BinaryResearchRow], *, reps: int, seed: int
) -> Iterable[list[BinaryResearchRow]]:
    if reps <= 0:
        raise ResearchBacktestError("BOOTSTRAP_REPS_INVALID")
    by_season: dict[int, list[BinaryResearchRow]] = {}
    for row in rows:
        by_season.setdefault(row.season, []).append(row)
    seasons = sorted(by_season)
    if len(seasons) < 2:
        raise ResearchBacktestError("BOOTSTRAP_REQUIRES_MULTIPLE_SEASONS")
    rng = Random(int(seed))
    for _ in range(reps):
        sample: list[BinaryResearchRow] = []
        for _ in seasons:
            picked = seasons[rng.randrange(len(seasons))]
            sample.extend(by_season[picked])
        yield sample


def _quantile(values: Sequence[float], q: float) -> float:
    if not values:
        raise ResearchBacktestError("EMPTY_QUANTILE")
    if not 0.0 <= q <= 1.0:
        raise ResearchBacktestError("QUANTILE_OUT_OF_RANGE")
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    pos = q * (len(ordered) - 1)
    lo = int(pos)
    hi = min(len(ordered) - 1, lo + 1)
    frac = pos - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


def paired_market_bootstrap(
    rows: Iterable[Mapping[str, Any] | BinaryResearchRow], *,
    reps: int = 2000, seed: int = 20260903,
) -> dict[str, Any]:
    """Season-cluster bootstrap of model minus benchmark probability loss."""
    data = [
        r for r in canonicalize_rows(rows)
        if r.outcome in (0, 1) and r.benchmark_p is not None
    ]
    if not data:
        raise ResearchBacktestError("NO_PAIRED_BENCHMARK_ROWS")
    if len({r.season for r in data}) < 2:
        raise ResearchBacktestError("PAIRED_BOOTSTRAP_REQUIRES_MULTIPLE_SEASONS")

    def deltas(sample: Sequence[BinaryResearchRow]) -> tuple[float, float]:
        return (
            brier_score(sample, probability=lambda r: r.model_p)
            - brier_score(sample, probability=lambda r: r.benchmark_p),
            log_loss(sample, probability=lambda r: r.model_p)
            - log_loss(sample, probability=lambda r: r.benchmark_p),
        )

    point_brier, point_log = deltas(data)
    briers: list[float] = []
    logs: list[float] = []
    for sample in _cluster_bootstrap_samples(data, reps=reps, seed=seed):
        bd, ld = deltas(sample)
        briers.append(bd)
        logs.append(ld)
    return {
        "paired_n": len(data),
        "seasons": sorted({r.season for r in data}),
        "brier_delta_model_minus_benchmark": point_brier,
        "brier_delta_ci95": [_quantile(briers, 0.025), _quantile(briers, 0.975)],
        "log_loss_delta_model_minus_benchmark": point_log,
        "log_loss_delta_ci95": [_quantile(logs, 0.025), _quantile(logs, 0.975)],
        "interpretation": "NEGATIVE_IS_BETTER",
        "bootstrap_cluster": "season",
        "bootstrap_reps": reps,
        "bootstrap_seed": int(seed),
    }


def completed_season_walkforward(
    rows: Iterable[Mapping[str, Any] | BinaryResearchRow], *,
    min_train_seasons: int = 3,
) -> tuple[dict[str, Any], ...]:
    """Return immutable fold identities; model fitting occurs outside this evaluator."""
    data = canonicalize_rows(rows)
    seasons = sorted({r.season for r in data})
    if min_train_seasons < 1:
        raise ResearchBacktestError("MIN_TRAIN_SEASONS_INVALID")
    folds: list[dict[str, Any]] = []
    for test in seasons:
        train = [s for s in seasons if s < test]
        if len(train) < min_train_seasons:
            continue
        folds.append({
            "train_seasons": train,
            "test_season": test,
            "train_n": sum(r.season in train for r in data),
            "test_n": sum(r.season == test for r in data),
        })
    if not folds:
        raise ResearchBacktestError("NO_ELIGIBLE_WALKFORWARD_FOLDS")
    return tuple(folds)


def compare_candidate_to_incumbent(
    candidate_rows: Iterable[Mapping[str, Any] | BinaryResearchRow], *,
    min_rows: int = 200,
    min_seasons: int = 3,
    max_ece: float = 0.025,
    calibration_slope_range: tuple[float, float] = (0.90, 1.10),
    max_abs_calibration_intercept: float = 0.03,
    reps: int = 2000,
    seed: int = 20260903,
) -> dict[str, Any]:
    """Fail-closed research verdict. This never grants production eligibility."""
    data = canonicalize_rows(candidate_rows)
    summary = summarize_binary_market(data)
    reasons: list[str] = []
    if int(summary["n_binary"]) < min_rows:
        reasons.append("MIN_ROWS_NOT_MET")
    if len(summary["seasons"]) < min_seasons:
        reasons.append("MIN_SEASONS_NOT_MET")
    if float(summary["ece"]) > max_ece:
        reasons.append("ECE_GATE_FAILED")
    slope = summary.get("calibration_slope")
    intercept = summary.get("calibration_intercept")
    if slope is None or not calibration_slope_range[0] <= float(slope) <= calibration_slope_range[1]:
        reasons.append("CALIBRATION_SLOPE_GATE_FAILED")
    if intercept is None or abs(float(intercept)) > max_abs_calibration_intercept:
        reasons.append("CALIBRATION_INTERCEPT_GATE_FAILED")

    paired = None
    if int(summary["benchmark_n"]) > 0 and len({
        r.season for r in data if r.benchmark_p is not None and r.outcome in (0, 1)
    }) >= 2:
        paired = paired_market_bootstrap(data, reps=reps, seed=seed)
        if paired["brier_delta_ci95"][1] >= 0.0:
            reasons.append("BRIER_NOT_CONFIDENTLY_BETTER_THAN_BENCHMARK")
        if paired["log_loss_delta_ci95"][1] >= 0.0:
            reasons.append("LOG_LOSS_NOT_CONFIDENTLY_BETTER_THAN_BENCHMARK")
    else:
        reasons.append("PAIRED_BENCHMARK_EVIDENCE_MISSING")

    return {
        "research_status": "CHALLENGER_PASSES_RESEARCH_BAR" if not reasons else "RESEARCH_BAR_NOT_CLEARED",
        "production_eligibility_changed": False,
        "summary": summary,
        "paired_benchmark": paired,
        "reasons": reasons,
    }
