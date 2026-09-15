"""Fail-closed temporal evaluation contracts for SportsEdge research candidates.

This module is sport-neutral plumbing only.  It does not fit a model, create
Model_P, consume a validation attempt, change a Truth Gate, or promote a
market.  Callers must bind the returned split/cluster identity into their own
immutable evidence artifacts before it can support later evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True)
class EvaluationRow:
    event_id: str
    observed_at: datetime
    probability: float
    outcome: int


@dataclass(frozen=True)
class TemporalWindows:
    train_end: datetime
    calibration_start: datetime
    calibration_end: datetime
    test_start: datetime

    def validate(self) -> None:
        points = (self.train_end, self.calibration_start, self.calibration_end, self.test_start)
        if any(point.tzinfo is None or point.utcoffset() is None for point in points):
            raise ValueError("TEMPORAL_WINDOW_NAIVE_TIMESTAMP")
        if not (self.train_end < self.calibration_start <= self.calibration_end < self.test_start):
            raise ValueError("TEMPORAL_WINDOW_OVERLAP_OR_REORDER")


def _validate_row(row: EvaluationRow) -> None:
    if not row.event_id.strip():
        raise ValueError("EVENT_ID_MISSING")
    if row.observed_at.tzinfo is None or row.observed_at.utcoffset() is None:
        raise ValueError("ROW_NAIVE_TIMESTAMP")
    if not 0.0 <= row.probability <= 1.0:
        raise ValueError("PROBABILITY_OUT_OF_RANGE")
    if row.outcome not in (0, 1):
        raise ValueError("OUTCOME_NOT_BINARY")


def partition_untouched(rows: Iterable[EvaluationRow], windows: TemporalWindows) -> dict[str, tuple[EvaluationRow, ...]]:
    """Partition without shuffle; reject boundary gaps instead of guessing."""
    windows.validate()
    result: dict[str, list[EvaluationRow]] = {"train": [], "calibration": [], "test": []}
    for row in sorted(rows, key=lambda r: (r.observed_at, r.event_id)):
        _validate_row(row)
        if row.observed_at <= windows.train_end:
            result["train"].append(row)
        elif windows.calibration_start <= row.observed_at <= windows.calibration_end:
            result["calibration"].append(row)
        elif row.observed_at >= windows.test_start:
            result["test"].append(row)
        else:
            raise ValueError("ROW_IN_UNDECLARED_TEMPORAL_GAP")
    if any(not result[name] for name in result):
        raise ValueError("TEMPORAL_PARTITION_EMPTY")
    return {name: tuple(values) for name, values in result.items()}


def require_disjoint_event_ids(partitions: Mapping[str, Sequence[EvaluationRow]]) -> None:
    """Prevent the same game/event from leaking across train/calibration/test."""
    seen: dict[str, str] = {}
    for partition in ("train", "calibration", "test"):
        for row in partitions.get(partition, ()):
            previous = seen.setdefault(row.event_id, partition)
            if previous != partition:
                raise ValueError(f"EVENT_CROSSES_TEMPORAL_PARTITIONS:{row.event_id}")


def event_clusters(rows: Sequence[EvaluationRow]) -> tuple[tuple[int, ...], ...]:
    """Return deterministic event clusters for game-level resampling/inference.

    Multiple snapshots/markets from one game remain one sampling unit.  This
    function intentionally returns cluster membership rather than performing a
    bootstrap so downstream evidence policy controls seeds/resample counts.
    """
    clusters: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        _validate_row(row)
        clusters.setdefault(row.event_id, []).append(index)
    return tuple(tuple(clusters[event_id]) for event_id in sorted(clusters))


def evaluation_identity(partitions: Mapping[str, Sequence[EvaluationRow]]) -> str:
    """Content identity for an append-only evaluation input snapshot."""
    payload = []
    for partition in ("train", "calibration", "test"):
        for row in partitions.get(partition, ()):
            payload.append({
                "partition": partition,
                "event_id": row.event_id,
                "observed_at": row.observed_at.isoformat(),
                "probability": row.probability,
                "outcome": row.outcome,
            })
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
