"""Frozen NFL V1 rejects negative fields; signed-yard support needs a versioned challenger."""
import pytest

from sportsedge.sports.nfl import live_role_source as m


def test_frozen_v1_negative_yards_and_counts_rejected():
    for field in ("rushing_yards", "receiving_yards", "passing_yards",
                  "carries", "targets", "rushing_tds", "attempts"):
        with pytest.raises(m.NFLContextError, match="nonnegative finite required"):
            m._number(-1, field)
    with pytest.raises(m.NFLContextError, match="nonnegative finite required"):
        m._number(float("nan"), "rushing_yards")


def test_frozen_v1_nonnegative_role_rate_unchanged():
    rows = [(1.0, {"rushing_yards": 4, "carries": 2}),
            (1.0, {"rushing_yards": 30, "carries": 6})]
    assert m._weighted_rate(rows, "rushing_yards", "carries") == 34 / 8
    assert m._weighted_rate([(1.0, {"rushing_yards": 0, "carries": 2})],
                            "rushing_yards", "carries") == 0.0
