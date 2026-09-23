"""PIT-safe NHL play-by-play shot ingestion contract.

This is a source-normalization boundary, not an xG model. It preserves event-time
context needed by a later fitted model while rejecting post-puck-drop snapshots
from pregame feature construction.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any, Iterable


def _utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class NHLShotEvent:
    game_id: str
    event_id: str
    event_time_utc: str
    team_id: str
    shooter_id: str
    goalie_id: str | None
    x: float
    y: float
    shot_type: str
    strength_state: str
    is_goal: bool
    is_rebound: bool
    is_rush: bool
    source: str
    source_version: str

    def __post_init__(self) -> None:
        _utc(self.event_time_utc)
        if not all((self.game_id, self.event_id, self.team_id, self.shooter_id, self.shot_type,
                    self.strength_state, self.source, self.source_version)):
            raise ValueError("shot identity and provenance are required")
        if not math.isfinite(self.x) or not math.isfinite(self.y):
            raise ValueError("shot coordinates must be finite")


@dataclass(frozen=True)
class NHLShotSnapshot:
    game_id: str
    puck_drop: str
    captured_at: str
    source: str
    source_version: str
    events: tuple[NHLShotEvent, ...]

    def __post_init__(self) -> None:
        puck = _utc(self.puck_drop)
        captured = _utc(self.captured_at)
        if not captured < puck:
            raise ValueError("PIT violation: pregame shot snapshot must predate puck drop")
        if not self.game_id or not self.source or not self.source_version:
            raise ValueError("snapshot provenance required")
        if any(e.game_id != self.game_id for e in self.events):
            raise ValueError("cross-game event in snapshot")
        if any(_utc(e.event_time_utc) >= puck for e in self.events):
            raise ValueError("future/current-game event leaked into pregame snapshot")


def normalize_shot_rows(rows: Iterable[dict[str, Any]], *, game_id: str,
                        source: str, source_version: str) -> tuple[NHLShotEvent, ...]:
    """Normalize already-retrieved public PBP rows without inventing missing fields."""
    out: list[NHLShotEvent] = []
    required = ("event_id", "event_time_utc", "team_id", "shooter_id", "x", "y",
                "shot_type", "strength_state", "is_goal", "is_rebound", "is_rush")
    for row in rows:
        missing = [key for key in required if key not in row or row[key] is None]
        if missing:
            raise ValueError(f"shot row missing required fields: {','.join(missing)}")
        out.append(NHLShotEvent(
            game_id=game_id,
            event_id=str(row["event_id"]),
            event_time_utc=str(row["event_time_utc"]),
            team_id=str(row["team_id"]),
            shooter_id=str(row["shooter_id"]),
            goalie_id=None if row.get("goalie_id") is None else str(row["goalie_id"]),
            x=float(row["x"]), y=float(row["y"]), shot_type=str(row["shot_type"]),
            strength_state=str(row["strength_state"]), is_goal=bool(row["is_goal"]),
            is_rebound=bool(row["is_rebound"]), is_rush=bool(row["is_rush"]),
            source=source, source_version=source_version,
        ))
    return tuple(sorted(out, key=lambda e: (_utc(e.event_time_utc), e.event_id)))


def shot_snapshot_sha256(snapshot: NHLShotSnapshot) -> str:
    payload = {
        "game_id": snapshot.game_id, "puck_drop": snapshot.puck_drop,
        "captured_at": snapshot.captured_at, "source": snapshot.source,
        "source_version": snapshot.source_version,
        "events": [e.__dict__ for e in snapshot.events],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()
