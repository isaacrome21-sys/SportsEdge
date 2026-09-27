from sportsedge.sports.nba.player_stats import NBAPlayerStatRole, simulate_player_stats
from sportsedge.sports.nba.simulation import NBAGameState, simulate_game_paths


def role():
    return NBAPlayerStatRole("p1","HOME","v1",34.0,3.0,0.22,0.18,0.16,0.075)


def game():
    return simulate_game_paths(NBAGameState("g",100,116,112),simulations=300,seed=11)


def test_player_paths_are_deterministic_and_bounded_by_team_points():
    g=game(); a=simulate_player_stats(g,role()); b=simulate_player_stats(g,role())
    assert a == b
    assert all(p <= team for p,team in zip(a.points,g.home_regulation))
    assert all(3*t <= p for t,p in zip(a.threes,a.points))
    assert all(0 <= m <= 48 for m in a.minutes)


def test_combo_props_are_same_path_sums():
    p=simulate_player_stats(game(),role(),seed=3)
    assert p.pra == tuple(x+y+z for x,y,z in zip(p.points,p.rebounds,p.assists))
    assert p.pr == tuple(x+y for x,y in zip(p.points,p.rebounds))
    assert p.pa == tuple(x+y for x,y in zip(p.points,p.assists))
    assert p.ra == tuple(x+y for x,y in zip(p.rebounds,p.assists))


def test_bad_role_fails_closed():
    import pytest
    with pytest.raises(ValueError):
        NBAPlayerStatRole("p","HOME","v",49,1,.2,.1,.1,.1).validate()
    with pytest.raises(ValueError):
        NBAPlayerStatRole("p","X","v",30,1,.2,.1,.1,.1).validate()
