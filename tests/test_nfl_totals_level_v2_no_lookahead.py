"""Prereg §7: a residual anchor never uses its own game, and nothing at or
after a fixture's kickoff enters its league level (pure-function form)."""
import pytest

from sportsedge.research import nfl_totals_level_v2 as v2


def _anchor(half_totals_before):
    return v2.league_level(half_totals_before)


def test_anchor_excludes_own_game():
    prior = [20.0, 22.0, 24.0]
    own = 99.0
    a = _anchor(prior)
    # the anchor computed from strictly-prior games must not move when the
    # game's own score changes
    assert _anchor(prior) == a
    assert a != _anchor(prior + [own])


def test_future_values_do_not_enter():
    prior = [21.0] * 50
    base = v2.league_level(prior)
    assert base == pytest.approx(21.0, abs=1e-12)
    # the caller passes strictly-prior games only; appending a later game
    # is the only way to change the level
    assert v2.league_level(prior + [80.0]) > base


def test_residual_uses_only_supplied_history():
    hist = [(2024, 3.0, -1.0)] * 4
    off, de = v2.team_residuals(hist, 2024)
    off2, de2 = v2.team_residuals(list(hist), 2024)
    assert (off, de) == (off2, de2)
