from sportsedge.sports.nhl.simulation import NHLGameState, deterministic_seed, simulate_game_paths


def test_simulation_is_deterministic_and_same_path():
    state = NHLGameState("game-1", 3.1, 2.7, 0.54)
    a = simulate_game_paths(state, simulations=500, model_version="fit-a")
    b = simulate_game_paths(state, simulations=500, model_version="fit-a")
    assert a == b
    assert a.seed == deterministic_seed(state, "fit-a")
    assert a.simulations == 500


def test_regulation_ties_get_exactly_one_deciding_final_goal():
    paths = simulate_game_paths(NHLGameState("tie-heavy", 0.0, 0.0, 1.0), simulations=25)
    assert set(paths.home_regulation) == {0}
    assert set(paths.away_regulation) == {0}
    assert set(paths.home_final) == {1}
    assert set(paths.away_final) == {0}


def test_non_tied_regulation_scores_are_not_mutated():
    paths = simulate_game_paths(NHLGameState("game-2", 3.0, 2.0), simulations=500)
    for hr, ar, hf, af in zip(paths.home_regulation, paths.away_regulation, paths.home_final, paths.away_final):
        if hr != ar:
            assert (hf, af) == (hr, ar)
        else:
            assert hf + af == hr + ar + 1
            assert hf != af


def test_invalid_state_fails_closed():
    try:
        simulate_game_paths(NHLGameState("", 3.0, 2.0))
    except ValueError as exc:
        assert "game_id" in str(exc)
    else:
        raise AssertionError("missing game_id must fail")
