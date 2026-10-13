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
