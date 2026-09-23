"""PIT-safe historical NBA possession targets.

Possession targets are provider observations from completed regulation play, never
reconstructed from sportsbook totals or final score alone. Pregame features must
still be timestamped strictly before tipoff; targets are attached only for
training/evaluation after the game has completed.
"""
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
from typing import Iterable


@dataclass(frozen=True)
class NBAPossessionObservation:
    game_id: str
    tipoff: datetime
    feature_as_of: datetime
    observed_at: datetime
    possessions: float
    source: str
    source_version: str

    def validate(self) -> None:
        if not all((self.game_id, self.source, self.source_version)):
            raise ValueError("possession observation identity/source are required")
        for name, value in (("tipoff", self.tipoff), ("feature_as_of", self.feature_as_of), ("observed_at", self.observed_at)):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.feature_as_of >= self.tipoff:
            raise ValueError("feature_as_of must be strictly before tipoff")
        if self.observed_at <= self.tipoff:
            raise ValueError("possession target must be observed after tipoff")
        if not math.isfinite(self.possessions) or self.possessions <= 0:
            raise ValueError("possessions must be finite and positive")


def possession_digest(rows: Iterable[NBAPossessionObservation]) -> str:
    ordered=tuple(sorted(rows, key=lambda r:(r.tipoff, r.game_id)))
    if not ordered:
        raise ValueError("possession observations are required")
    for row in ordered: row.validate()
    payload=[{
        "game_id":r.game_id,
        "tipoff":r.tipoff.isoformat(),
        "feature_as_of":r.feature_as_of.isoformat(),
        "observed_at":r.observed_at.isoformat(),
        "possessions":r.possessions,
        "source":r.source,
        "source_version":r.source_version,
    } for r in ordered]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def bind_possession_targets(training_rows, observations: Iterable[NBAPossessionObservation]):
    """Return deterministic (training row, observed possessions) pairs by game id."""
    obs={}
    for row in observations:
        row.validate()
        if row.game_id in obs:
            raise ValueError("duplicate possession observation for game")
        obs[row.game_id]=row
    pairs=[]
    for training in sorted(training_rows, key=lambda r:(r.tipoff, r.game_id)):
        training.validate()
        target=obs.get(training.game_id)
        if target is None:
            continue
        if target.tipoff != training.tipoff:
            raise ValueError("possession/training tipoff mismatch")
        if target.feature_as_of != training.feature_as_of:
            raise ValueError("possession/training feature timestamp mismatch")
        pairs.append((training, target.possessions))
    if not pairs:
        raise ValueError("no possession targets bind to training rows")
    return tuple(pairs)
