"""Bind PIT-safe availability snapshots to fitted NBA player roles.

This module joins availability context to historical role fitting without inventing
injury probabilities. OUT is zero minutes; AVAILABLE/PROBABLE use PIT history;
QUESTIONABLE/DOUBTFUL require an explicit caller-supplied minutes scenario.
"""
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Iterable, Mapping

from .availability import NBAAvailabilitySnapshot, availability_digest, latest_availability
from .player_history import NBAPlayerBoxObservation, fit_player_role
from .player_stats import NBAPlayerStatRole


@dataclass(frozen=True)
class NBAAvailabilityBoundRoles:
    roles: tuple[NBAPlayerStatRole, ...]
    availability_sha256: str
    as_of: datetime
    version: str


def bind_availability_roles(
    history: Iterable[NBAPlayerBoxObservation],
    availability: Iterable[NBAAvailabilitySnapshot],
    *,
    player_teams: Mapping[str, str],
    as_of: datetime,
    uncertain_minutes: Mapping[str, tuple[float, float]] | None = None,
) -> NBAAvailabilityBoundRoles:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    if not player_teams:
        raise ValueError("player_teams are required")
    rows = tuple(availability)
    latest = latest_availability(rows, as_of=as_of)
    digest = availability_digest(tuple(latest.values()))
    overrides = uncertain_minutes or {}
    roles = []
    for player_id, side in sorted(player_teams.items()):
        if player_id not in latest:
            raise ValueError(f"no PIT-eligible availability for player {player_id}")
        snap = latest[player_id]
        status = snap.status.strip().upper()
        override = overrides.get(player_id)
        if status in {"QUESTIONABLE", "DOUBTFUL"} and override is None:
            raise ValueError(f"uncertain status requires explicit minutes scenario for {player_id}")
        if status not in {"QUESTIONABLE", "DOUBTFUL"} and override is not None:
            raise ValueError(f"minutes scenario only allowed for uncertain player {player_id}")
        roles.append(fit_player_role(history, player_id=player_id, team=side, as_of=as_of,
                                     status=status, uncertain_minutes_override=override))
    payload = {"availability_sha256": digest, "as_of": as_of.isoformat(),
               "roles": [(r.player_id, r.version, r.minutes_mean, r.minutes_sd) for r in roles]}
    version = "NBA_AVAILABILITY_BOUND_ROLES_V1:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:12]
    return NBAAvailabilityBoundRoles(tuple(roles), digest, as_of, version)
