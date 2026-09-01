"""Point-in-time snapshot contract for LIVE_ENGINE_V1."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from typing import Any, Mapping

from .live_policy import LIVE_POLICY_VERSION, assert_market_blind


class LiveSnapshotError(ValueError):
    pass


@dataclass(frozen=True)
class LivePITSnapshot:
    event_id: str
    sport: str
    source_as_of: datetime
    retrieved_at: datetime
    pit_cutoff: datetime
    state_sequence: str
    provider: str
    raw_state: Mapping[str, Any]
    model_features: Mapping[str, Any]
    policy_version: str = LIVE_POLICY_VERSION

    def validate(self) -> None:
        for name, value in (
            ("source_as_of", self.source_as_of),
            ("retrieved_at", self.retrieved_at),
            ("pit_cutoff", self.pit_cutoff),
        ):
            if value.tzinfo is None:
                raise LiveSnapshotError(f"{name} must be timezone-aware")
        if not self.event_id or not self.sport or not self.provider or not self.state_sequence:
            raise LiveSnapshotError("event_id/sport/provider/state_sequence are required")
        if self.source_as_of > self.retrieved_at:
            raise LiveSnapshotError("source_as_of cannot be after retrieved_at")
        if self.source_as_of > self.pit_cutoff:
            raise LiveSnapshotError("state occurs after LIVE_PIT_CUTOFF")
        if self.policy_version != LIVE_POLICY_VERSION:
            raise LiveSnapshotError("snapshot policy version mismatch")
        try:
            assert_market_blind(dict(self.model_features))
        except ValueError as exc:
            raise LiveSnapshotError(str(exc)) from exc

    @property
    def snapshot_id(self) -> str:
        self.validate()
        payload = {
            "event_id": self.event_id,
            "sport": self.sport,
            "source_as_of": self.source_as_of.isoformat(),
            "pit_cutoff": self.pit_cutoff.isoformat(),
            "state_sequence": self.state_sequence,
            "provider": self.provider,
            "policy_version": self.policy_version,
            "raw_state": self.raw_state,
            "model_features": self.model_features,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        return sha256(encoded).hexdigest()


def assert_feature_timestamps_at_or_before_cutoff(
    feature_as_of: Mapping[str, datetime], pit_cutoff: datetime
) -> None:
    if pit_cutoff.tzinfo is None:
        raise LiveSnapshotError("pit_cutoff must be timezone-aware")
    offenders = []
    for name, timestamp in feature_as_of.items():
        if timestamp.tzinfo is None or timestamp > pit_cutoff:
            offenders.append(name)
    if offenders:
        raise LiveSnapshotError("features violate LIVE_PIT_CUTOFF: " + ", ".join(sorted(offenders)))
