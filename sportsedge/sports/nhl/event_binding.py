"""PIT-safe binding of historical NHL roles to shared roster event paths."""
from dataclasses import dataclass
from datetime import datetime, timezone

from .role_binding import NHLBoundRosterRoles
from .roster_events import NHLRosterEventPaths, simulate_roster_events
from .simulation import NHLGamePaths


def _utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("role cutoff must be timezone-aware")
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class NHLBoundEventPaths:
    events: NHLRosterEventPaths
    team: str
    role_cutoff: str
    history_sha256: str
    role_version: str


def simulate_bound_roster_events(
    game: NHLGamePaths,
    bound: NHLBoundRosterRoles,
    *,
    team: str,
    puck_drop: str,
    version: str,
    seed: int | None = None,
) -> NHLBoundEventPaths:
    if team not in {"HOME", "AWAY"}:
        raise ValueError("team must be HOME or AWAY")
    if not version:
        raise ValueError("event binding version required")
    cutoff = _utc(bound.cutoff)
    drop = _utc(puck_drop)
    if cutoff >= drop:
        raise ValueError("PIT violation: role cutoff must predate puck drop")
    if not bound.history_sha256 or not bound.version:
        raise ValueError("role history provenance required")
    roles = list(bound.event_roles)
    if not roles or any(r.team != team for r in roles):
        raise ValueError("bound event roles must match requested team")
    if any(_utc(r.captured_at) != cutoff for r in roles):
        raise ValueError("event role cutoff mismatch")
    events = simulate_roster_events(
        game, roles, team=team,
        version=f"{version}:{bound.version}:{bound.history_sha256}",
        seed=seed,
    )
    team_goals = game.home_regulation if team == "HOME" else game.away_regulation
    for i, total in enumerate(team_goals):
        if sum(values[i] for values in events.goals.values()) != total:
            raise AssertionError("player goal paths do not reconcile to team regulation goals")
    return NHLBoundEventPaths(
        events=events, team=team, role_cutoff=bound.cutoff,
        history_sha256=bound.history_sha256, role_version=bound.version,
    )
