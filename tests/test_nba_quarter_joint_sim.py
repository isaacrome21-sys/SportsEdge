"""Coherence, leakage and push-settlement tests for the NBA quarter simulation.
Synthetic deterministic unit inputs only (not evidence)."""
import random
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from sportsedge.sports.nba.quarter_joint_sim import (
    QuarterGame, calibrate, markets, settle_over, simulate)

T0 = datetime(2024, 10, 22, 23, 0, tzinfo=timezone.utc)


def qgames(n=60, seed=3):
    rng = random.Random(seed)
    out = []
    for i in range(n):
        h = tuple(rng.randint(22, 34) for _ in range(4))
        a = tuple(rng.randint(22, 34) for _ in range(4))
        if sum(h) == sum(a):
            h, a = h + (12,), a + (9,)
        out.append(QuarterGame(str(1000 + i), T0 + timedelta(hours=i), h, a))
    return out


AS_OF = T0 + timedelta(hours=40)


def test_calibration_ignores_future_and_order():
    g = qgames()
    base = calibrate(g, AS_OF)
    sh = g[:]
    random.Random(9).shuffle(sh)
    fut = [QuarterGame("f%d" % i, AS_OF + timedelta(hours=i), (60, 60, 60, 60), (5, 5, 5, 5))
           for i in range(30)]
    assert calibrate(sh + fut, AS_OF) == base
    assert abs(sum(base.shares) - 1) < 1e-9


def test_all_markets_coherent_from_one_path_set():
    cal = calibrate(qgames(), AS_OF)
    H, A = simulate(cal, 114.0, 110.0, n=5000, seed=1)
    m = markets(H, A)
    assert np.array_equal(m["total"], m["home"] + m["away"])
    assert np.array_equal(m["h1_total"], H[:, 0] + H[:, 1] + A[:, 0] + A[:, 1])
    assert (m["h1_total"] <= m["total"]).all() and (m["q1_total"] <= m["h1_total"]).all()
    assert not (m["margin"] == 0).any()  # OT resolves every regulation tie
    assert m["home_ml"] == pytest.approx(float((m["margin"] > 0).mean()))
    assert 0 < m["went_ot"] < 0.2


def test_mean_tracks_rating_input():
    cal = calibrate(qgames(), AS_OF)
    lo = markets(*simulate(cal, 105, 105, n=4000, seed=2))["total"].mean()
    hi = markets(*simulate(cal, 120, 120, n=4000, seed=2))["total"].mean()
    assert hi - lo == pytest.approx(30 * cal.reg_share, abs=2.0)


def test_push_settlement_whole_and_half_lines():
    v = np.array([220, 221, 221, 222])
    s = settle_over(v, 221)
    assert s == {"over": 0.25, "under": 0.25, "push": 0.5}
    assert settle_over(v, 221.5)["push"] == 0.0


def test_fail_closed_without_prior_data():
    with pytest.raises(ValueError, match="FEWER_THAN_30"):
        calibrate(qgames(), T0 + timedelta(hours=5))
    with pytest.raises(ValueError, match="AS_OF_TIMEZONE"):
        calibrate(qgames(), AS_OF.replace(tzinfo=None))
