import random
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.sports.cbb.asof_ratings import CBBGame, fit_asof, illinois_block, possessions, trainable

T0 = datetime(2024, 11, 4, 23, tzinfo=timezone.utc)
STRENGTH = {"150": 12, "57": 6, "2226": 0, "305": -4, "2130": -10, "99": 3}


def _games(n_days=30, seed=1):
    rng = random.Random(seed)
    ids = list(STRENGTH)
    out = []
    k = 0
    for d in range(n_days):
        rng.shuffle(ids)
        for i in range(0, 6, 2):
            h, a = ids[i], ids[i + 1]
            pos = 68 + rng.gauss(0, 3)
            hp = round(pos * (1.05 + (STRENGTH[h] - STRENGTH[a]) / 200) + 2 + rng.gauss(0, 8))
            ap = round(pos * 1.05 + rng.gauss(0, 8))
            out.append(CBBGame(f"g{k}", T0 + timedelta(days=d, hours=i), h, a, hp, ap, pos, d % 5 == 0))
            k += 1
    return out


def _sig(r):
    return (r.games_used, round(r.hca, 9), tuple(sorted((t, round(v, 9)) for t, v in r.off.items())))


def test_future_and_unfinished_games_do_not_leak_and_order_invariant():
    g = _games()
    cut = T0 + timedelta(days=20)
    base = _sig(fit_asof(g, cut))
    sh = g[:]
    random.Random(3).shuffle(sh)
    fut = [CBBGame("f1", cut + timedelta(hours=1), "150", "57", 200, 0, 70, False),
           CBBGame("f2", cut - timedelta(hours=1), "150", "57", 200, 0, 70, False),  # started, not final
           CBBGame("f3", cut - timedelta(days=2), "150", "57", 200, 0, 70, False, completed=False)]
    assert _sig(fit_asof(sh + fut, cut)) == base


def test_final_buffer():
    g = CBBGame("x", T0, "1", "2", 70, 60, 68, False)
    assert not trainable(g, T0 + timedelta(hours=2)) and trainable(g, T0 + timedelta(hours=3))


def test_ratings_recover_order_and_home_court():
    r = fit_asof(_games(60), T0 + timedelta(days=61))
    order = sorted(STRENGTH, key=lambda t: r.off[t] - r.deff[t], reverse=True)
    assert order[0] == "150" and order[-1] == "2130"
    assert r.hca > 0
    p_home = r.predict("2226", "99", neutral=False)
    p_neu = r.predict("2226", "99", neutral=True)
    assert p_home["margin"] > p_neu["margin"]
    assert p_home["play_authority"] is False


def test_illinois_excluded_by_id_home_and_away():
    r = fit_asof(_games(40), T0 + timedelta(days=41))
    for h, a in (("150", "2130"), ("305", "57")):
        p = r.predict(h, a, neutral=False)
        assert p["status"] == "BLOCKED" and p["reason"] == "ILLINOIS_COLLEGE_EXCLUDED"
    assert illinois_block("150", "57") is None
    assert illinois_block("2466", "150") is None  # Northwestern State is not Illinois


def test_possessions_formula():
    assert possessions(59, 13, 8, 22) == pytest.approx(59 - 13 + 8 + 0.475 * 22)


def _mismatch_games():
    """Strong hosts vs weak non-D1 visitors at home; true HCA = 3."""
    rng = random.Random(7)
    st = dict(STRENGTH, nd1=-30, nd2=-30)
    out, k = [], 0
    for d in range(50):
        pairs = [("150", "nd1"), ("57", "nd2")] if d < 15 else []
        ids = list(STRENGTH)
        rng.shuffle(ids)
        pairs += [(ids[i], ids[i + 1]) for i in range(0, 6, 2)]
        for h, a in pairs:
            pos = 68.0
            neutral = d % 4 == 0 and d >= 15
            margin = (st[h] - st[a]) * 0.7 + (0 if neutral else 3) + rng.gauss(0, 6)
            out.append(CBBGame(f"m{k}", T0 + timedelta(days=d, hours=k % 5), h, a,
                               round(72 + margin / 2), round(72 - margin / 2), pos, neutral))
            k += 1
    return out


def test_v2_joint_hca_removes_mismatch_bias_and_pools_non_d1():
    g = _mismatch_games()
    cut = T0 + timedelta(days=51)
    v1 = fit_asof(g, cut)
    v2 = fit_asof(g, cut, version="v2", d1_ids=STRENGTH.keys())
    assert v1.hca > 6  # raw home margin is confounded by cupcake games
    assert abs(v2.hca - 3) < 2
    assert "NON_D1" in v2.n and "nd1" not in v2.n
    assert v2.predict("150", "nd2", neutral=False)["margin"] > 10
    with pytest.raises(ValueError):
        fit_asof(g, cut, version="v2")


def test_v2_leakage_invariance():
    g = _mismatch_games()
    cut = T0 + timedelta(days=30)
    base = fit_asof(g, cut, version="v2", d1_ids=STRENGTH.keys())
    fut = [CBBGame("z", cut - timedelta(hours=1), "150", "57", 300, 0, 70, False)]
    again = fit_asof(list(reversed(g)) + fut, cut, version="v2", d1_ids=STRENGTH.keys())
    assert round(base.hca, 9) == round(again.hca, 9) and base.off == again.off
