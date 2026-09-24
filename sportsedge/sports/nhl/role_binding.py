"""Bind PIT-safe NHL historical role shares to coherent roster simulators.

This module is deliberately mechanical: it maps already-fitted empirical role
shares into the explicit inputs consumed by roster goal/assist and SOG engines.
It does not add priors, market prices, hidden weights, or performance claims.
"""
from dataclasses import dataclass
from .role_history import NHLHistoricalRoleShare
from .roster_events import NHLRosterEventRole
from .roster_shots import NHLRosterShotRole


@dataclass(frozen=True)
class NHLBoundRosterRoles:
    event_roles: tuple[NHLRosterEventRole, ...]
    shot_roles: tuple[NHLRosterShotRole, ...]
    cutoff: str
    history_sha256: str
    version: str


def bind_historical_roles(
    shares: tuple[NHLHistoricalRoleShare, ...], *, team: str,
    lineup_status: str, active_player_ids: set[str] | frozenset[str],
) -> NHLBoundRosterRoles:
    """Bind eligible active skaters without manufacturing missing-player weights."""
    if team not in {"HOME", "AWAY"}:
        raise ValueError("team must be HOME or AWAY")
    if lineup_status not in {"CONFIRMED", "PROJECTED"}:
        raise ValueError("invalid lineup status")
    if not shares or not active_player_ids:
        raise ValueError("historical shares and active roster required")
    if len({s.player_id for s in shares}) != len(shares):
        raise ValueError("duplicate historical player")
    cutoffs = {s.cutoff for s in shares}
    digests = {s.history_sha256 for s in shares}
    versions = {s.version for s in shares}
    teams = {s.team_id for s in shares}
    if len(cutoffs) != 1 or len(digests) != 1 or len(versions) != 1 or len(teams) != 1:
        raise ValueError("historical shares must come from one fitted team snapshot")

    selected = [s for s in shares if s.player_id in active_player_ids]
    if not selected:
        raise ValueError("active roster has no eligible historical shares")
    selected.sort(key=lambda s: s.player_id)
    source_version = f"{next(iter(versions))}:{next(iter(digests))}"
    captured_at = next(iter(cutoffs))

    events = tuple(NHLRosterEventRole(
        player_id=s.player_id, team=team, captured_at=captured_at,
        source=s.source, version=source_version,
        goal_weight=s.goal_weight,
        primary_assist_weight=s.primary_assist_weight,
        secondary_assist_weight=s.secondary_assist_weight,
        lineup_status=lineup_status,
    ) for s in selected)
    shots = tuple(NHLRosterShotRole(
        player_id=s.player_id, team=team, captured_at=captured_at,
        source=s.source, version=source_version,
        shot_weight=s.shot_weight, lineup_status=lineup_status,
    ) for s in selected)
    if sum(r.goal_weight for r in events) <= 0:
        raise ValueError("active roster lacks positive historical goal weight")
    if sum(r.shot_weight for r in shots) <= 0:
        raise ValueError("active roster lacks positive historical shot weight")
    return NHLBoundRosterRoles(
        events, shots, captured_at, next(iter(digests)), next(iter(versions)))