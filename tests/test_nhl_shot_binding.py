import pytest

from sportsedge.sports.nhl.role_binding import bind_historical_roles
from sportsedge.sports.nhl.role_history import NHLHistoricalRoleShare
from sportsedge.sports.nhl.shot_binding import simulate_bound_shots
from sportsedge.sports.nhl.team_shots import NHLTeamShotParameters


def _share(player, team, shot):
    return NHLHistoricalRoleShare(
        player_id=player, team_id=team, cutoff="2026-01-02T00:00:00Z",
        source="nhl@v1", version="role-v1", games=20, shot_weight=shot,
        goal_weight=.2, primary_assist_weight=.2, secondary_assist_weight=.1,
        history_sha256=("a" if team == "H" else "b") * 64,
    )


def _roles():
    home=bind_historical_roles((_share("h1","H",3),_share("h2","H",1)),
        team="HOME", lineup_status="CONFIRMED", active_player_ids={"h1","h2"})
    away=bind_historical_roles((_share("a1","A",2),_share("a2","A",2)),
        team="AWAY", lineup_status="PROJECTED", active_player_ids={"a1","a2"})
    return home, away


def test_bound_sog_is_deterministic_and_reconciles_every_path():
    home,away=_roles(); params=NHLTeamShotParameters("sog-fit-v1",31,29)
    x=simulate_bound_shots("g1",params,home,away,simulations=100)
    y=simulate_bound_shots("g1",params,home,away,simulations=100)
    assert x == y
    for i in range(100):
        assert sum(v[i] for v in x.home_roster.shots.values()) == x.team_paths.home[i]
        assert sum(v[i] for v in x.away_roster.shots.values()) == x.team_paths.away[i]


def test_bound_sog_requires_same_pit_cutoff():
    home,away=_roles()
    from dataclasses import replace
    away=replace(away,cutoff="2026-01-03T00:00:00Z")
    with pytest.raises(ValueError,match="PIT cutoff"):
        simulate_bound_shots("g1",NHLTeamShotParameters("v1",30,30),home,away,simulations=10)
