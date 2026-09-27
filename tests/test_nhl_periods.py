from sportsedge.sports.nhl.simulation import NHLGameState, simulate_game_paths
from sportsedge.sports.nhl.periods import NHLPeriodParameters, simulate_period_paths, period_three_way, period_total_over


def test_period_paths_are_deterministic_and_sum_to_regulation():
    game = simulate_game_paths(NHLGameState("g", 3.1, 2.7), simulations=500, seed=17)
    p = NHLPeriodParameters("fixture-v1", (.32, .34, .34))
    a = simulate_period_paths(game, p)
    b = simulate_period_paths(game, p)
    assert a == b
    for periods, total in zip(a.home, game.home_regulation):
        assert sum(periods) == total
    for periods, total in zip(a.away, game.away_regulation):
        assert sum(periods) == total


def test_period_markets_have_valid_probability_mass():
    game = simulate_game_paths(NHLGameState("g", 3.1, 2.7), simulations=1000, seed=18)
    paths = simulate_period_paths(game, NHLPeriodParameters("fixture-v1", (.33, .33, .34)))
    for period in (1, 2, 3):
        assert abs(sum(period_three_way(paths, period)) - 1) < 1e-12
        assert abs(sum(period_total_over(paths, period, 2.0)) - 1) < 1e-12


def test_period_parameters_fail_closed():
    game = simulate_game_paths(NHLGameState("g", 3, 3), simulations=10, seed=1)
    try:
        simulate_period_paths(game, NHLPeriodParameters("", (.33, .33, .34)))
        assert False
    except ValueError:
        pass
