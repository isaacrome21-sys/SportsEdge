import pytest

from sportsedge.sports.nfl import live_role_source as m


def test_negative_single_game_yards_accepted_counts_still_rejected():
    assert m._number(-3, "rushing_yards") == -3.0
    assert m._number("-7", "receiving_yards") == -7.0
    assert m._number(-2, "passing_yards") == -2.0
    for f in ("carries", "targets", "rushing_tds", "attempts"):
        with pytest.raises(m.NFLContextError, match="nonnegative finite required"):
            m._number(-1, f)
    with pytest.raises(m.NFLContextError, match="finite required"):
        m._number(float("nan"), "rushing_yards")


def test_role_rate_with_negative_game_and_floor():
    rows = [(1.0, {"rushing_yards": -4, "carries": 2}), (1.0, {"rushing_yards": 30, "carries": 6})]
    assert m._weighted_rate(rows, "rushing_yards", "carries") == 26 / 8
    one = [(1.0, {"rushing_yards": -4, "carries": 2})]
    assert m._weighted_rate(one, "rushing_yards", "carries") == 0.0
