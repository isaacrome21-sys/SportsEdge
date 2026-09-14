from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from itertools import product
from typing import Callable, Iterable

from .objective import ObjectiveWeights


@dataclass(frozen=True)
class HistoricalSlate:
    slate_id: str
    lock_time: datetime
    artifact_path: str

    def validate(self) -> None:
        if not self.slate_id.strip() or not self.artifact_path.strip():
            raise ValueError("DFS_TUNING_SLATE_IDENTITY_REQUIRED")
        if self.lock_time.tzinfo is None or self.lock_time.utcoffset() is None:
            raise ValueError("DFS_TUNING_LOCK_TIMEZONE_REQUIRED")


@dataclass(frozen=True)
class BacktestMetrics:
    slate_count: int
    roi: float
    top_one_percent_rate: float
    cash_rate: float
    max_drawdown: float

    def validate(self) -> None:
        if self.slate_count < 1:
            raise ValueError("DFS_TUNING_METRIC_SLATE_COUNT_INVALID")
        if not 0.0 <= self.top_one_percent_rate <= 1.0:
            raise ValueError("DFS_TUNING_TOP1_INVALID")
        if not 0.0 <= self.cash_rate <= 1.0:
            raise ValueError("DFS_TUNING_CASH_INVALID")
        if self.max_drawdown < 0.0:
            raise ValueError("DFS_TUNING_DRAWDOWN_INVALID")


@dataclass(frozen=True)
class TuningResult:
    selected: ObjectiveWeights
    baseline: ObjectiveWeights
    promoted: bool
    reason: str
    train_metrics: BacktestMetrics
    holdout_metrics: BacktestMetrics
    baseline_holdout_metrics: BacktestMetrics
    train_slate_count: int
    holdout_slate_count: int


def objective_grid(
    baseline: ObjectiveWeights,
    *,
    upside_values: Iterable[float] = (0.24, 0.34, 0.44),
    low_ownership_values: Iterable[float] = (0.04, 0.08, 0.12),
    chalk_penalty_values: Iterable[float] = (0.02, 0.05, 0.08),
    correlation_values: Iterable[float] = (0.75, 1.0, 1.25),
) -> tuple[ObjectiveWeights, ...]:
    rows: list[ObjectiveWeights] = []
    seen: set[tuple[float, float, float, float]] = set()
    for upside, low_own, chalk, corr in product(
        upside_values, low_ownership_values, chalk_penalty_values, correlation_values
    ):
        key = (float(upside), float(low_own), float(chalk), float(corr))
        if key in seen:
            continue
        seen.add(key)
        candidate = replace(
            baseline,
            version=(
                f"DFS_OBJECTIVE_CANDIDATE_U{upside:.3f}_L{low_own:.3f}_"
                f"C{chalk:.3f}_R{corr:.3f}"
            ),
            upside_weight=float(upside),
            low_ownership_weight=float(low_own),
            chalk_penalty_weight=float(chalk),
            correlation_weight=float(corr),
        )
        candidate.validate()
        rows.append(candidate)
    return tuple(rows)


def _train_score(metrics: BacktestMetrics) -> tuple[float, float, float, float]:
    """Research ranking only; this score has no promotion authority."""
    metrics.validate()
    return (
        metrics.roi,
        metrics.top_one_percent_rate,
        metrics.cash_rate,
        -metrics.max_drawdown,
    )


def chronological_holdout_tune(
    *,
    slates: Iterable[HistoricalSlate],
    baseline: ObjectiveWeights,
    candidates: Iterable[ObjectiveWeights],
    evaluator: Callable[[ObjectiveWeights, tuple[HistoricalSlate, ...]], BacktestMetrics],
    holdout_fraction: float = 0.25,
    min_holdout_slates: int = 20,
    max_roi_worsening: float = 0.10,
    max_drawdown_worsening: float = 0.15,
) -> TuningResult:
    """Rank DFS objective candidates without granting automatic promotion.

    Contest ROI/top-1% over a modest number of slates are too noisy to be a
    positive promotion gate. This function still performs a chronological split,
    ranks research candidates on the training window, and evaluates the frozen
    candidate on untouched holdout. ROI and drawdown are treated only as vetoes.

    Projection-model promotion is governed separately by
    ``projection_promotion.evaluate_projection_promotion`` using player-level
    calibration/error evidence. Until a separate pre-registered policy-validation
    contract exists for objective weights, the frozen baseline remains live.
    """
    baseline.validate()
    if not 0.10 <= holdout_fraction <= 0.50:
        raise ValueError("DFS_TUNING_HOLDOUT_FRACTION_INVALID")
    rows = sorted(tuple(slates), key=lambda s: (s.lock_time, s.slate_id))
    for slate in rows:
        slate.validate()
    if len({s.slate_id for s in rows}) != len(rows):
        raise ValueError("DFS_TUNING_DUPLICATE_SLATE_ID")
    holdout_n = max(min_holdout_slates, int(round(len(rows) * holdout_fraction)))
    if holdout_n >= len(rows):
        raise ValueError("DFS_TUNING_HISTORY_TOO_SMALL")
    train = tuple(rows[:-holdout_n])
    holdout = tuple(rows[-holdout_n:])
    if max(s.lock_time for s in train) >= min(s.lock_time for s in holdout):
        raise ValueError("DFS_TUNING_TEMPORAL_SPLIT_INVALID")

    candidate_rows = tuple(candidates)
    if not candidate_rows:
        raise ValueError("DFS_TUNING_CANDIDATES_EMPTY")
    train_results: list[tuple[ObjectiveWeights, BacktestMetrics]] = []
    for weights in candidate_rows:
        weights.validate()
        metrics = evaluator(weights, train)
        metrics.validate()
        if metrics.slate_count != len(train):
            raise ValueError("DFS_TUNING_TRAIN_COUNT_MISMATCH")
        train_results.append((weights, metrics))
    selected, selected_train = max(train_results, key=lambda row: _train_score(row[1]))

    selected_holdout = evaluator(selected, holdout)
    baseline_holdout = evaluator(baseline, holdout)
    selected_holdout.validate()
    baseline_holdout.validate()
    if selected_holdout.slate_count != len(holdout) or baseline_holdout.slate_count != len(holdout):
        raise ValueError("DFS_TUNING_HOLDOUT_COUNT_MISMATCH")

    roi_veto_ok = selected_holdout.roi >= baseline_holdout.roi - max_roi_worsening
    drawdown_veto_ok = (
        selected_holdout.max_drawdown
        <= baseline_holdout.max_drawdown + max_drawdown_worsening
    )
    vetoes = [
        name
        for name, ok in (("ROI", roi_veto_ok), ("DRAWDOWN", drawdown_veto_ok))
        if not ok
    ]
    reason = (
        "RESEARCH_CANDIDATE_BLOCKED_BY_VETO:" + ",".join(vetoes)
        if vetoes
        else "RESEARCH_CANDIDATE_ONLY:NO_POLICY_PROMOTION_AUTHORITY"
    )
    return TuningResult(
        selected=baseline,
        baseline=baseline,
        promoted=False,
        reason=reason,
        train_metrics=selected_train,
        holdout_metrics=selected_holdout,
        baseline_holdout_metrics=baseline_holdout,
        train_slate_count=len(train),
        holdout_slate_count=len(holdout),
    )
