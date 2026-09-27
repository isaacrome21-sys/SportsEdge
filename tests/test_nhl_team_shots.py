import pytest
from sportsedge.sports.nhl.team_shots import NHLTeamShotParameters, simulate_team_shot_paths


def test_team_sog_paths_are_deterministic_and_aligned():
    params=NHLTeamShotParameters("sog-fit-v1",31.5,28.25)
    a=simulate_team_shot_paths("g1",params,simulations=200)
    b=simulate_team_shot_paths("g1",params,simulations=200)
    assert a == b
    assert len(a.home) == len(a.away) == 200
    assert all(isinstance(x,int) and x >= 0 for x in a.home+a.away)


def test_team_sog_requires_explicit_versioned_positive_means():
    with pytest.raises(ValueError, match="version"):
        simulate_team_shot_paths("g1",NHLTeamShotParameters("",30,30),simulations=10)
    with pytest.raises(ValueError, match="positive"):
        simulate_team_shot_paths("g1",NHLTeamShotParameters("v1",0,30),simulations=10)


def test_team_sog_seed_changes_with_fitted_inputs():
    a=simulate_team_shot_paths("g1",NHLTeamShotParameters("v1",30,30),simulations=20)
    b=simulate_team_shot_paths("g1",NHLTeamShotParameters("v2",30,30),simulations=20)
    assert a.seed != b.seed


def test_team_sog_rejects_missing_game_or_bad_sim_count():
    p=NHLTeamShotParameters("v1",30,30)
    with pytest.raises(ValueError, match="game_id"):
        simulate_team_shot_paths("",p,simulations=10)
    with pytest.raises(ValueError, match="positive"):
        simulate_team_shot_paths("g1",p,simulations=0)
