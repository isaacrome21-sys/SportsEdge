import numpy as np
import pytest

from sportsedge.sports.nba.simulation import GameState, simulate_game


def _state(**changes):
    base = dict(
        game_id="nba-test-1",
        as_of_utc="2026-09-22T06:45:00Z",
        model_version="nba-score-v0",
        expected_possessions=100.0,
        home_points_per_100=116.0,
        away_points_per_100=112.0,
        home_advantage_points=2.0,
    )
    base.update(changes)
    return GameState(**base)


def test_replay_is_deterministic_and_integer_valued():
    a = simulate_game(_state(), 1000)
    b = simulate_game(_state(), 1000)
    assert a.seed == b.seed
    assert np.array_equal(a.home_points, b.home_points)
    assert np.array_equal(a.away_points, b.away_points)
    assert np.issubdtype(a.home_points.dtype, np.integer)


def test_provenance_changes_seed_and_paths():
    a = simulate_game(_state(), 500)
    b = simulate_game(_state(model_version="nba-score-v1"), 500)
    assert a.seed != b.seed
    assert not np.array_equal(a.home_points, b.home_points)


def test_shared_game_state_supports_all_full_game_derivatives():
    paths = simulate_game(_state(), 500)
    margin = paths.home_points - paths.away_points
    total = paths.home_points + paths.away_points
    assert len(margin) == len(total) == 500
    assert paths.home_points.shape == paths.away_points.shape


def test_invalid_state_fails_closed():
    with pytest.raises(ValueError):
        simulate_game(_state(expected_possessions=0), 100)
    with pytest.raises(ValueError):
        simulate_game(_state(team_efficiency_sd=-1), 100)
    with pytest.raises(ValueError):
        simulate_game(_state(), 0)
