from sportsedge.sports.nba.simulation import NBAGameState, deterministic_seed, simulate_game_paths


def state():
    return NBAGameState("g1", 99.5, 116.0, 112.0, 5.5, 1.0, 10.0)


def test_deterministic_shared_paths():
    a=simulate_game_paths(state(),simulations=500,model_version="m1")
    b=simulate_game_paths(state(),simulations=500,model_version="m1")
    assert a == b
    assert a.seed == deterministic_seed(state(),"m1")
    assert len(a.possessions) == 500


def test_final_paths_never_tie_and_regulation_is_preserved():
    p=simulate_game_paths(state(),simulations=1000,seed=7)
    assert all(h != a for h,a in zip(p.home_final,p.away_final))
    assert all(fh >= rh and fa >= ra for rh,ra,fh,fa in zip(p.home_regulation,p.away_regulation,p.home_final,p.away_final))


def test_bad_state_and_sim_count_fail_closed():
    import pytest
    with pytest.raises(ValueError):
        simulate_game_paths(NBAGameState("",99,110,110),simulations=10)
    with pytest.raises(ValueError):
        simulate_game_paths(state(),simulations=0)
