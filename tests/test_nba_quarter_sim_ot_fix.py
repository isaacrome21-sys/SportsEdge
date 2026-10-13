import numpy as np

from sportsedge.sports.nba.quarter_joint_sim import OT_FIX_GRID, simulate, simulate_margin_scaled
from datetime import datetime, timedelta, timezone

from sportsedge.sports.nba.quarter_joint_sim import QuarterGame, calibrate


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


def test_c_one_reproduces_v1_distribution_and_shrink_raises_ties():
    cal = _cal()
    H1, A1 = simulate(cal, 112.0, 110.0, n=20000, seed=4)
    Hc, Ac = simulate_margin_scaled(cal, 112.0, 110.0, c=1.0, n=20000, seed=4)
    assert abs((H1.sum(1) + A1.sum(1)).mean() - (Hc.sum(1) + Ac.sum(1)).mean()) < 0.3
    Hs, As = simulate_margin_scaled(cal, 112.0, 110.0, c=0.6, n=20000, seed=4)
    ot = lambda H: (H[:, 4:].sum(1) > 0).mean()
    assert ot(Hs) > ot(Hc)
    assert abs((Hs.sum(1) + As.sum(1)).mean() - (Hc.sum(1) + Ac.sum(1)).mean()) < 1.0


def test_grid_and_bounds():
    assert OT_FIX_GRID[0] == 0.6 and OT_FIX_GRID[-1] == 1.0 and len(OT_FIX_GRID) == 21
    try:
        simulate_margin_scaled(_cal(), 110.0, 110.0, c=0.0)
        assert False
    except ValueError:
        pass
