"""Collector promotion rules based on durable data-branch evidence.

Run logs alone are never sufficient. A collector is production-proven only when
its most recent N durable manifests are PASS and required artifacts are present
and non-empty for each corresponding execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class CollectorRunEvidence:
    run_id: str
    manifest_status: str
    artifacts: Mapping[str, int]


@dataclass(frozen=True)
class CollectorPromotionResult:
    promoted: bool
    consecutive_passes: int
    required_passes: int
    blockers: tuple[str, ...]


def evaluate_collector_promotion(
    runs: Iterable[CollectorRunEvidence],
    *,
    required_artifacts: Iterable[str],
    required_passes: int = 2,
) -> CollectorPromotionResult:
    if required_passes <= 0:
        raise ValueError("required_passes must be positive")
    required = tuple(str(x) for x in required_artifacts)
    if not required:
        raise ValueError("required_artifacts must not be empty")
    ordered = list(runs)
    blockers: list[str] = []
    streak = 0
    for run in reversed(ordered):
        if str(run.manifest_status).upper() != "PASS":
            if streak == 0:
                blockers.append(f"LATEST_MANIFEST_NOT_PASS:{run.run_id}:{run.manifest_status}")
            break
        missing = [name for name in required if int(run.artifacts.get(name, 0) or 0) <= 0]
        if missing:
            blockers.append(f"DURABLE_ARTIFACT_MISSING_OR_EMPTY:{run.run_id}:{','.join(missing)}")
            break
        streak += 1
        if streak >= required_passes:
            break
    if streak < required_passes and not blockers:
        blockers.append(f"INSUFFICIENT_CONSECUTIVE_DURABLE_PASSES:{streak}/{required_passes}")
    return CollectorPromotionResult(streak >= required_passes, streak, required_passes, tuple(blockers))
