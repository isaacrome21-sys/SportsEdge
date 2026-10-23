"""Unit checks for the NFL totals LEVEL v2 research candidate (prereg §7)."""
import math

import pytest

from sportsedge.research import nfl_totals_level_v2 as v2


def test_preregistered_constants():
    assert (v2.LEAGUE_HALF_LIFE_GAMES, v2.TEAM_HALF_LIFE_GAMES,
            v2.SEASON_CARRYOVER, v2.KAPPA, v2.LEAGUE_FALLBACK,
            v2.HFA_HALF, v2.TOTAL_SD) == (128.0, 6.0, 0.5, 3.0, 22.0, 0.75, 13.5)


def test_empty_history_fallbacks():
    assert v2.league_level([]) == 22.0
    assert v2.team_residuals([], 2024) == (0.0, 0.0)
    eh, ea = v2.expected_scores(22.0, (0.0, 0.0), (0.0, 0.0))
    assert (eh, ea) == (22.75, 21.25)


def test_league_half_life_identity():
    # oldest value sits exactly one half-life back -> weight 0.5
    vals = [10.0] + [0.0] * 127 + [20.0]
    # ages: 128 (w=.5), 127..1, 0 (w=1)
    w = [0.5 ** ((len(vals) - 1 - i) / 128.0) for i in range(len(vals))]
    assert w[0] == pytest.approx(0.5)
    expect = (0.5 * 10 + 20) / sum(w)
    assert v2.league_level(vals) == pytest.approx(expect, abs=1e-12)


def test_constant_history_returns_constant():
    assert v2.league_level([23.4] * 300) == pytest.approx(23.4, abs=1e-12)


def test_team_half_life_and_carryover():
    hist = [(2023, 6.0, 0.0)] + [(2024, 0.0, 0.0)] * 6
    # oldest game: age 6 -> 0.5, prior season -> x0.5 => 0.25
    weights = [0.25] + [0.5 ** ((5 - i) / 6.0) for i in range(6)]
    off, de = v2.team_residuals(hist, 2024)
    assert off == pytest.approx(0.25 * 6.0 / (sum(weights) + 3.0), abs=1e-12)
    assert de == 0.0


def test_shrinkage_toward_zero():
    off, _ = v2.team_residuals([(2024, 10.0, 0.0)], 2024)
    assert off == pytest.approx(10.0 / 4.0)


def test_future_season_row_rejected():
    with pytest.raises(ValueError):
        v2.team_residuals([(2025, 1.0, 1.0)], 2024)


def test_expected_scores_symmetry():
    eh, ea = v2.expected_scores(21.0, (2.0, -1.0), (1.0, 3.0))
    assert eh == pytest.approx(21.0 + (2.0 + 3.0) / 2 + 0.75)
    assert ea == pytest.approx(21.0 + (1.0 - 1.0) / 2 - 0.75)
    assert math.isfinite(eh + ea)
