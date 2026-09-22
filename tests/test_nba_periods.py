from sportsedge.sports.nba.periods import NBAPeriodParameters, simulate_period_paths, quarter_margin, quarter_total, half_margin, half_total
from sportsedge.sports.nba.simulation import NBAGameState, simulate_game_paths


def paths():
    return simulate_game_paths(NBAGameState("g",100,115,111),simulations=200,seed=9)


def test_period_paths_are_deterministic_and_sum_to_regulation():
    g=paths(); p=NBAPeriodParameters("v1",(0.25,0.25,0.25,0.25))
    a=simulate_period_paths(g,p); b=simulate_period_paths(g,p)
    assert a == b
    assert all(sum(q)==total for q,total in zip(a.home,g.home_regulation))
    assert all(sum(q)==total for q,total in zip(a.away,g.away_regulation))


def test_quarter_and_half_derivatives_share_paths():
    p=simulate_period_paths(paths(),NBAPeriodParameters("v1",(0.24,0.26,0.24,0.26)),seed=3)
    assert len(quarter_margin(p,1)) == 200
    assert len(quarter_total(p,4)) == 200
    assert len(half_margin(p,1)) == 200
    assert len(half_total(p,2)) == 200


def test_bad_period_parameters_fail_closed():
    import pytest
    with pytest.raises(ValueError):
        NBAPeriodParameters("",(0.25,)*4).validate()
    with pytest.raises(ValueError):
        NBAPeriodParameters("x",(0.2,)*4).validate()
