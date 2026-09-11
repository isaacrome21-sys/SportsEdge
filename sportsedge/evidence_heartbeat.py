"""Shared evidence-lane freshness evaluation for external watchdogs.

This module deliberately has no GitHub Actions dependency so the same logic can
be run by an external scheduler when Actions itself is unavailable.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class LaneState:
    name: str
    last_durable_at: datetime
    max_age_seconds: int

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("LANE_NAME_REQUIRED")
        if self.last_durable_at.tzinfo is None:
            raise ValueError("LANE_TIMESTAMP_MUST_BE_TIMEZONE_AWARE")
        if self.max_age_seconds <= 0:
            raise ValueError("LANE_MAX_AGE_MUST_BE_POSITIVE")


@dataclass(frozen=True)
class LaneFreshness:
    name: str
    last_durable_at: datetime
    age_seconds: float
    max_age_seconds: int
    stale: bool


@dataclass(frozen=True)
class EvidenceHeartbeatReport:
    lanes: tuple[LaneFreshness, ...]
    stale_lanes: tuple[LaneFreshness, ...]
    alert: bool
    shared_outage_signature: bool


def evaluate_lanes(
    lanes: list[LaneState] | tuple[LaneState, ...],
    *,
    now: datetime,
    shared_cutoff_tolerance_seconds: int = 12 * 3600,
) -> EvidenceHeartbeatReport:
    if now.tzinfo is None:
        raise ValueError("NOW_MUST_BE_TIMEZONE_AWARE")
    if shared_cutoff_tolerance_seconds < 0:
        raise ValueError("SHARED_CUTOFF_TOLERANCE_NEGATIVE")

    evaluated: list[LaneFreshness] = []
    for lane in lanes:
        age = (now - lane.last_durable_at).total_seconds()
        if age < 0:
            raise ValueError(f"FUTURE_DURABLE_TIMESTAMP:{lane.name}")
        evaluated.append(
            LaneFreshness(
                name=lane.name,
                last_durable_at=lane.last_durable_at,
                age_seconds=age,
                max_age_seconds=lane.max_age_seconds,
                stale=age > lane.max_age_seconds,
            )
        )

    stale = tuple(item for item in evaluated if item.stale)
    shared = False
    if len(stale) >= 2:
        timestamps = [item.last_durable_at.timestamp() for item in stale]
        shared = max(timestamps) - min(timestamps) <= shared_cutoff_tolerance_seconds

    return EvidenceHeartbeatReport(
        lanes=tuple(evaluated),
        stale_lanes=stale,
        alert=bool(stale),
        shared_outage_signature=shared,
    )
