"""Synthetic-only tests for NFL_RUSH_REC_PROPS_V1 (no real-data outcomes)."""
import importlib.util
import math
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("scr", HERE / "screen_nfl_rush_rec_props_v1.py")
scr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scr)
GRID = np.arange(-60, 701, dtype=float)


def test_seed_override_explicit_and_pinned_file_untouched():
    ev = scr.load_evaluator()
    assert ev.SEED == 20261028 == scr.SCREEN_SEED
    assert "SEED, RESAMPLES = 20261017, 2000" in scr.EVAL_PATH.read_text()


def test_data_hash_refusal(tmp_path):
    for n in scr.DATA_PINS:
        (tmp_path / n).write_bytes(b"x")
    with pytest.raises(SystemExit):
        scr.check_data(tmp_path)


def test_extra_file_refused(tmp_path):
    (tmp_path / "ps_2026.csv.gz").write_bytes(b"x")
    with pytest.raises(SystemExit):
        scr.check_data(tmp_path)


def test_cum_earlier_strict_and_fallback():
    c = scr.Cum()
    c.add(2020, 1, [1, 1, 0, 1]); c.add(2020, 2, [5, 1, 0, 1]); c.add(2021, 3, [9, 1, 0, 1])
    c.finalize()
    assert c.earlier(2020, 2)[0] == 1          # week 2 itself excluded
    assert c.earlier(2021, 3)[0] == 6          # no earlier 2021 weeks -> full 2020
    assert c.earlier(2021, 4)[0] == 9


def test_yards_cdf_moments():
    n_hat, rate, r_n, s2 = 15.0, 4.5, 8.0, 40.0
    cdf = scr.m_cdf("RUSH_YDS", n_hat, rate, r_n, s2, GRID)
    pdf = np.diff(np.concatenate([[0.0], cdf]))
    mean = float((pdf * GRID).sum())
    assert abs(mean - n_hat * rate) < 1.0
    assert cdf[-1] > 0.999 and np.all(np.diff(cdf) >= -1e-12)


def test_receptions_cdf_mixture():
    cdf = scr.m_cdf("RECEPTIONS", 6.0, 0.65, 10.0, None, GRID)
    k = np.arange(0, 40)
    pmf = np.diff(np.concatenate([[0.0], cdf[60:100]]))
    assert abs((pmf * k).sum() - 6.0 * 0.65) < 1e-3
    assert np.all(cdf[:60] == 0.0) and cdf[-1] > 1 - 1e-6


def test_poisson_when_r_inf():
    a = scr.m_cdf("REC_YDS", 7.0, 8.0, math.inf, 60.0, GRID)
    assert np.all(np.isfinite(a))


def test_deciles_split_matches_incumbent_rule():
    rows = [{"p": i / 100, "over": float(i % 2)} for i in range(100)]
    d = scr.deciles(rows, "p")
    assert [x["n"] for x in d] == [10] * 10
    assert d[9]["mean_p_over"] > d[0]["mean_p_over"]


def _toy(week5_carries):
    from collections import defaultdict
    games = defaultdict(lambda: defaultdict(list))
    team_v = defaultdict(lambda: defaultdict(lambda: {"carries": 0.0, "targets": 0.0}))
    for w in range(1, 6):
        for pid, c in (("A", 10.0 if w < 5 else week5_carries), ("B", 5.0)):
            row = {k: 0.0 for k in scr.COLS}
            row.update(carries=c, rushing_yards=4 * c)
            games[2020][pid].append((w, "RB", "T", row))
            team_v[2020][(w, "T")]["carries"] += c
    inc = {2020: [(w, "A", [10.0 * 4] * (w - 1), 0.0) for w in range(4, 6)]}
    return games, team_v, inc


def test_point_in_time_excludes_priced_week():
    out = []
    for c5 in (10.0, 99.0):
        g, tv, inc = _toy(c5)
        pools = scr.build_pools("RUSH_YDS", g, tv, inc)
        out.append(scr.point_in_time("RUSH_YDS", g, tv, pools, 2020, "A", 5))
    assert out[0]["n_hat"] == out[1]["n_hat"] and out[0]["rate"] == out[1]["rate"]
