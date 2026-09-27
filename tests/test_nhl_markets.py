import math

from sportsedge.sports.nhl.markets import (
    game_total_over,
    home_moneyline,
    home_puck_line,
    home_regulation_three_way,
    team_total_over,
)
from sportsedge.sports.nhl.simulation import NHLGameState, simulate_game_paths


def _paths():
    return simulate_game_paths(NHLGameState("market-fixture", 3.2, 2.6, 0.55), simulations=2000, model_version="test")


def _assert_mass(outcome):
    assert math.isclose(outcome.win + outcome.push + outcome.loss, 1.0, abs_tol=1e-12)
    assert 0 <= outcome.win <= 1
    assert 0 <= outcome.push <= 1
    assert 0 <= outcome.loss <= 1


def test_full_game_markets_share_one_score_distribution():
    paths = _paths()
    ml = home_moneyline(paths)
    puck = home_puck_line(paths, -1.5)
    total = game_total_over(paths, 5.5)
    home_tt = team_total_over(paths, home=True, line=2.5)
    away_tt = team_total_over(paths, home=False, line=2.5)
    for outcome in (ml, puck, total, home_tt, away_tt):
        _assert_mass(outcome)
    assert ml.push == 0.0
    assert total.push == 0.0


def test_regulation_three_way_preserves_draw_mass_instead_of_reusing_final_ml():
    paths = simulate_game_paths(NHLGameState("draw-fixture", 0.0, 0.0, 1.0), simulations=20)
    home, draw, away = home_regulation_three_way(paths)
    assert (home, draw, away) == (0.0, 1.0, 0.0)
    assert home_moneyline(paths).win == 1.0


def test_integer_lines_preserve_push_mass():
    paths = simulate_game_paths(NHLGameState("push-fixture", 0.0, 0.0, 1.0), simulations=20)
    # Every final path is home 1, away 0.
    assert home_puck_line(paths, -1.0).push == 1.0
    assert game_total_over(paths, 1.0).push == 1.0
    assert team_total_over(paths, home=True, line=1.0).push == 1.0


def test_market_derivation_is_deterministic():
    paths = _paths()
    assert game_total_over(paths, 6.0) == game_total_over(paths, 6.0)
    assert home_puck_line(paths, 1.5) == home_puck_line(paths, 1.5)
