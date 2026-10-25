"""Regression tests: NBARatings.update() must refuse implausible finals loudly.

Found by the Oct 24, 2026 backtest sweep: update() validated nothing, and the
ratings state is checkpointed across cards, so one malformed final (NaN/inf
from a bad parse, a negative or self-game row) permanently and silently
poisoned every rating. These tests pin the fail-closed behavior.
"""
import math

import pytest

from sportsedge.sports.nba.ratings_model import NBARatings


def _seeded() -> NBARatings:
    r = NBARatings()
    r.update("A", "B", 110, 100)
    r.update("C", "A", 105, 102)
    return r


def _snapshot(r: NBARatings):
    return (dict(r.off), dict(r.dfn), r.league, r.hca)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"),
                                 -1, -0.5, 201, 300, "110", None, True])
def test_update_refuses_implausible_scores(bad):
    r = _seeded()
    before = _snapshot(r)
    with pytest.raises(ValueError):
        r.update("A", "B", bad, 100)
    with pytest.raises(ValueError):
        r.update("A", "B", 100, bad)
    assert _snapshot(r) == before


def test_update_refuses_self_game():
    r = _seeded()
    before = _snapshot(r)
    with pytest.raises(ValueError):
        r.update("A", "A", 110, 100)
    assert _snapshot(r) == before


def test_update_accepts_legitimate_finals():
    r = _seeded()
    r.update("A", "B", 186, 180)   # all-time record is 186 (DET, 1983, 3OT)
    r.update("B", "C", 0, 0)       # a shutout is implausible but not impossible data-wise; 0 is a valid score value
    hp, ap = r.predict("A", "B")
    assert math.isfinite(hp) and math.isfinite(ap)
