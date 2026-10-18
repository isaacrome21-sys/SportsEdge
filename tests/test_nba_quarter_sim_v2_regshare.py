from datetime import datetime, timedelta, timezone

import numpy as np

from sportsedge.sports.nba.quarter_joint_sim import QuarterGame, calibrate, simulate, simulate_v2


def _cal():
    rng = np.random.default_rng(1)
    t0 = datetime(2024, 11, 1, tzinfo=timezone.utc)
    gs = []
    for i in range(200):
        h = tuple(int(x) for x in rng.normal(28, 5, 4)); a = tuple(int(x) for x in rng.normal(28, 5, 4))
        if i % 15 == 0:
            a = a[:3] + (a[3] + sum(h) - sum(a),); h, a = h + (11,), a + (9,)
        gs.append(QuarterGame(str(i), t0 + timedelta(hours=i), h, a))
    return calibrate(gs, t0 + timedelta(days=30))


def test_v2_matches_rating_total_and_preserves_margin():
    cal = _cal()
    H, A = simulate_v2(cal, 118.0, 110.0, n=20000, seed=3)
    assert abs((H.sum(1) + A.sum(1)).mean() - 228.0) < 0.6
    H1, A1 = simulate(cal, 118.0, 110.0, n=20000, seed=3)
    assert abs((H.sum(1) - A.sum(1)).mean() - (H1.sum(1) - A1.sum(1)).mean()) < 0.6


def test_v2_deterministic_and_no_ties():
    cal = _cal()
    a = simulate_v2(cal, 112.0, 112.0, n=3000, seed=9)
    b = simulate_v2(cal, 112.0, 112.0, n=3000, seed=9)
    assert (a[0] == b[0]).all() and (a[1] == b[1]).all()
    assert not (a[0].sum(1) == a[1].sum(1)).any()
