"""Bind versioned team-SOG paths to PIT-safe roster shot roles.

This is a coherence boundary only. It consumes already-fitted team SOG parameters
and historical player roles; it does not infer missing weights or use market data.
"""
from dataclasses import dataclass

from .role_binding import NHLBoundRosterRoles
from .roster_shots import NHLRosterShotPaths, simulate_roster_shots
from .team_shots import NHLTeamShotParameters, NHLTeamShotPaths, simulate_team_shot_paths


@dataclass(frozen=True)
class NHLBoundShotSimulation:
    team_paths: NHLTeamShotPaths
    home_roster: NHLRosterShotPaths
    away_roster: NHLRosterShotPaths


def simulate_bound_shots(
    game_id: str,
    params: NHLTeamShotParameters,
    home_roles: NHLBoundRosterRoles,
    away_roles: NHLBoundRosterRoles,
    *,
    simulations: int = 20_000,
) -> NHLBoundShotSimulation:
    """Produce one coherent team/player SOG simulation with deterministic provenance."""
    if home_roles.cutoff != away_roles.cutoff:
        raise ValueError("home and away role snapshots must share one PIT cutoff")
    if not home_roles.shot_roles or not away_roles.shot_roles:
        raise ValueError("both teams require supported roster shot roles")
    if any(r.team != "HOME" for r in home_roles.shot_roles):
        raise ValueError("home roster contains non-HOME role")
    if any(r.team != "AWAY" for r in away_roles.shot_roles):
        raise ValueError("away roster contains non-AWAY role")

    team_paths = simulate_team_shot_paths(game_id, params, simulations=simulations)
    home_version = f"{params.version}:{home_roles.version}:{home_roles.history_sha256}"
    away_version = f"{params.version}:{away_roles.version}:{away_roles.history_sha256}"
    home = simulate_roster_shots(
        team_paths.home, list(home_roles.shot_roles), team="HOME",
        version=home_version, game_seed=team_paths.seed,
    )
    away = simulate_roster_shots(
        team_paths.away, list(away_roles.shot_roles), team="AWAY",
        version=away_version, game_seed=team_paths.seed,
    )
    if any(sum(home.shots[p][i] for p in home.shots) != team_paths.home[i]
           for i in range(simulations)):
        raise RuntimeError("home roster SOG reconciliation failed")
    if any(sum(away.shots[p][i] for p in away.shots) != team_paths.away[i]
           for i in range(simulations)):
        raise RuntimeError("away roster SOG reconciliation failed")
    return NHLBoundShotSimulation(team_paths, home, away)
