import numpy as np
import pytest

from sportsedge.sports.nba.markets import (
    game_total_over,
    home_moneyline,
    home_spread,
    team_total_over,
)
from sportsedge.sports.nba.simulation import ScorePaths


def _paths():
    return ScorePaths(
        home_points=np.array([110, 100, 95, 120], dtype=np.int16),
        away_points=np.array([100, 100, 105, 110], dtype=np.int16),
        seed=7,
    )


def test_moneyline_preserves_tie_mass_until_ot_is_modeled():
    p = home_moneyline(_paths())
    assert (p.win, p.push, p.loss) == (0.5, 0.25, 0.25)


def test_spread_and_totals_derive_from_same_paths():
    spread = home_spread(_paths(), -10.0)
    total = game_total_over(_paths(), 210.0)
    assert (spread.win, spread.push, spread.loss) == (0.0, 0.5, 0.5)
    assert (total.win, total.push, total.loss) == (0.25, 0.5, 0.25)


def test_team_totals_preserve_integer_pushes():
    home = team_total_over(_paths(), home=True, line=100.0)
    away = team_total_over(_paths(), home=False, line=100.0)
    assert (home.win, home.push, home.loss) == (0.5, 0.25, 0.25)
    assert (away.win, away.push, away.loss) == (0.5, 0.5, 0.0)


def test_nonfinite_lines_fail_closed():
    with pytest.raises(ValueError):
        home_spread(_paths(), float("nan"))
    with pytest.raises(ValueError):
        game_total_over(_paths(), float("inf"))
