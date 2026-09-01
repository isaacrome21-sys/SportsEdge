"""Validation helpers for correlated within-game live snapshots."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import sqrt
from statistics import mean
from typing import Iterable


@dataclass(frozen=True)
class LiveEvaluationRow:
    event_id: str
    snapshot_id: str
    model_p: float
    market_p: float
    outcome: float
    clv: float | None = None
    pnl: float | None = None


@dataclass(frozen=True)
class ClusteredMetric:
    name: str
    value: float
    game_clusters: int
    snapshots: int
    cluster_standard_error: float | None = None
    t_stat: float | None = None


def _groups(rows: Iterable[LiveEvaluationRow]) -> dict[str, list[LiveEvaluationRow]]:
    groups: dict[str, list[LiveEvaluationRow]] = defaultdict(list)
    for row in rows:
        if not row.event_id:
            raise ValueError("event_id required for game-clustered validation")
        groups[row.event_id].append(row)
    return dict(groups)


def brier_vs_market(rows: Iterable[LiveEvaluationRow]) -> tuple[ClusteredMetric, ClusteredMetric]:
    rows = list(rows)
    groups = _groups(rows)
    if not groups:
        raise ValueError("no live evaluation rows")
    model_losses = [(r.model_p - r.outcome) ** 2 for r in rows]
    market_losses = [(r.market_p - r.outcome) ** 2 for r in rows]
    return (
        ClusteredMetric("model_brier", mean(model_losses), len(groups), len(rows)),
        ClusteredMetric("market_brier", mean(market_losses), len(groups), len(rows)),
    )


def clustered_mean(rows: Iterable[LiveEvaluationRow], field: str) -> ClusteredMetric:
    rows = list(rows)
    groups = _groups(rows)
    cluster_means = []
    total_values = []
    for event_rows in groups.values():
        values = [getattr(row, field) for row in event_rows if getattr(row, field) is not None]
        if values:
            cluster_means.append(mean(values))
            total_values.extend(values)
    if not cluster_means:
        raise ValueError(f"no values for {field}")
    estimate = mean(cluster_means)
    if len(cluster_means) < 2:
        se = None
        t_stat = None
    else:
        variance = sum((x - estimate) ** 2 for x in cluster_means) / (len(cluster_means) - 1)
        se = sqrt(variance / len(cluster_means))
        t_stat = None if se == 0 else estimate / se
    return ClusteredMetric(field, estimate, len(groups), len(total_values), se, t_stat)


def actionable_sample_status(rows: Iterable[LiveEvaluationRow], minimum_game_clusters: int) -> dict[str, int | bool]:
    rows = list(rows)
    games = len(_groups(rows))
    return {
        "snapshots": len(rows),
        "game_clusters": games,
        "minimum_game_clusters": int(minimum_game_clusters),
        "passes": games >= int(minimum_game_clusters),
    }
