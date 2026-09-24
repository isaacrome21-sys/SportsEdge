"""PIT-safe NBA availability snapshots for rotation/minutes decisions.

Availability is context, not a sportsbook-derived probability. A snapshot is usable
only when it was observed before the model as-of time. Uncertain statuses remain
uncertain; callers must provide an explicit minutes scenario rather than this module
inventing one.
"""
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Iterable

_ALLOWED = frozenset({"AVAILABLE", "PROBABLE", "QUESTIONABLE", "DOUBTFUL", "OUT"})


@dataclass(frozen=True)
class NBAAvailabilitySnapshot:
    player_id: str
    team_id: str
    status: str
    observed_at: datetime
    source: str
    source_version: str

    def validate(self) -> None:
        if not all((self.player_id, self.team_id, self.source, self.source_version)):
            raise ValueError("availability identity/source fields are required")
        if self.status.strip().upper() not in _ALLOWED:
            raise ValueError("unsupported NBA availability status")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")


def availability_digest(rows: Iterable[NBAAvailabilitySnapshot]) -> str:
    ordered = tuple(sorted(rows, key=lambda r: (r.observed_at, r.team_id, r.player_id)))
    if not ordered:
        raise ValueError("availability snapshots are required")
    for row in ordered:
        row.validate()
    payload = [{
        "player_id": r.player_id,
        "team_id": r.team_id,
        "status": r.status.strip().upper(),
        "observed_at": r.observed_at.isoformat(),
        "source": r.source,
        "source_version": r.source_version,
    } for r in ordered]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def latest_availability(rows: Iterable[NBAAvailabilitySnapshot], *, as_of: datetime) -> dict[str, NBAAvailabilitySnapshot]:
    """Return each player's latest strictly pre-as-of snapshot.

    Future/equal-time snapshots are ignored so a historical run cannot see news
    that was not yet available. Ties are deterministic and fail closed when two
    distinct statuses claim the same latest timestamp for one player.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    eligible: dict[str, list[NBAAvailabilitySnapshot]] = {}
    for row in rows:
        row.validate()
        if row.observed_at < as_of:
            eligible.setdefault(row.player_id, []).append(row)
    result: dict[str, NBAAvailabilitySnapshot] = {}
    for player_id, candidates in eligible.items():
        latest_time = max(r.observed_at for r in candidates)
        latest = [r for r in candidates if r.observed_at == latest_time]
        statuses = {r.status.strip().upper() for r in latest}
        teams = {r.team_id for r in latest}
        if len(statuses) != 1 or len(teams) != 1:
            raise ValueError(f"conflicting latest availability snapshot for {player_id}")
        result[player_id] = sorted(latest, key=lambda r: (r.source, r.source_version))[0]
    return result


def availability_status(rows: Iterable[NBAAvailabilitySnapshot], *, player_id: str, as_of: datetime) -> str:
    latest = latest_availability(rows, as_of=as_of)
    if player_id not in latest:
        raise ValueError(f"no PIT-eligible availability for player {player_id}")
    return latest[player_id].status.strip().upper()
