"""Unit tests for the MLB_BATTER_RATES_V1 design screen helpers.

All fixtures are synthetic; no network and no pinned data files are used.
The screen itself lives in research/mlb_batter_successor_screen_20261028/.
"""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_SCREEN_PATH = (
    Path(__file__).resolve().parents[1]
    / "research" / "mlb_batter_successor_screen_20261028" / "run_screen.py"
)
_spec = importlib.util.spec_from_file_location("mlb_batter_rates_screen",
                                               _SCREEN_PATH)
screen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(screen)


# ---------------------------------------------------------------- devig ---

def test_devig_fair_pair_is_half():
    assert screen.devig_over(2.0, 2.0) == pytest.approx(0.5)


def test_devig_removes_margin_proportionally():
    # raw implied 2/3 and 0.4 -> normalized 0.625
    assert screen.devig_over(1.5, 2.5) == pytest.approx(0.625)


# ------------------------------------------------------------- shrinkage ---

def test_shrunk_rate_no_history_is_league_mean():
    assert screen.shrunk_rate(0.0, 0.0, mu=0.9) == pytest.approx(0.9)


def test_shrunk_rate_moves_toward_sample_with_evidence():
    lam = screen.shrunk_rate(40.0, 20.0, mu=1.0)  # sample mean 2.0
    assert 1.0 < lam < 2.0
    lam_many = screen.shrunk_rate(4000.0, 2000.0, mu=1.0)
    assert lam_many == pytest.approx(2.0, abs=0.02)


# ------------------------------------------------------------ count law ---

def test_count_sf_poisson_known_values():
    # P(X > 0.5) for Poisson(1) = 1 - e^-1; P(X > 1.5) = 1 - 2e^-1
    assert screen.count_sf(1.0, 1.0, 0.5) == pytest.approx(1 - math.exp(-1))
    assert screen.count_sf(1.0, 1.0, 1.5) == pytest.approx(1 - 2 * math.exp(-1))


def test_count_sf_nb_has_fatter_tail_than_poisson():
    p_nb = screen.count_sf(1.0, 2.0, 2.5)
    p_pois = screen.count_sf(1.0, 1.0, 2.5)
    assert p_nb > p_pois


def test_count_sf_monotone_in_rate_and_bounded():
    vals = [screen.count_sf(lam, 1.3, 1.5) for lam in (0.2, 0.8, 1.5, 3.0)]
    assert vals == sorted(vals)
    assert all(0.0 <= v <= 1.0 for v in vals)


def test_count_sf_zero_rate_is_zero():
    assert screen.count_sf(0.0, 1.5, 0.5) == 0.0


# ------------------------------------------------------------ main line ---

def _lines(rows):
    return pd.DataFrame(rows, columns=["game_id", "player", "market",
                                       "line", "n_quotes", "p_over_close"])


def test_main_line_picks_most_quoted():
    df = _lines([
        ["g1", "a", "player hits", 0.5, 900, 0.80],
        ["g1", "a", "player hits", 1.5, 5000, 0.42],
        ["g1", "a", "player hits", 2.5, 300, 0.10],
    ])
    out = screen.select_main_line(df)
    assert len(out) == 1 and out.iloc[0]["line"] == 1.5


def test_main_line_tie_breaks_to_balanced_then_lower():
    df = _lines([
        ["g1", "a", "player hits", 0.5, 1000, 0.81],
        ["g1", "a", "player hits", 1.5, 1000, 0.44],
        ["g1", "b", "player hits", 1.5, 1000, 0.60],
        ["g1", "b", "player hits", 2.5, 1000, 0.40],
    ])
    out = screen.select_main_line(df).set_index("player")
    assert out.loc["a", "line"] == 1.5   # 0.44 closer to 0.50 than 0.81
    assert out.loc["b", "line"] == 1.5   # equal balance -> lower line


# ------------------------------------------------------------- bootstrap ---

def test_cluster_bootstrap_constant_delta_collapses():
    games = np.array(["g1", "g2", "g3"])
    point, lo, hi = screen.cluster_bootstrap_ci(
        games, np.array([2.0, 4.0, 6.0]), np.array([10.0, 20.0, 30.0]),
        reps=200, seed=1)
    assert point == pytest.approx(0.2)
    assert lo == pytest.approx(0.2) and hi == pytest.approx(0.2)


# --------------------------------------------------------------- verdict ---

def _row(n=1000, c2=True, c3=True, c4=True):
    return {"n": n, "c2_vs_market_pass": c2, "c3_vs_simple_pass": c3,
            "c4_calibration_pass": c4}


def test_verdict_all_pass_is_design_pass():
    assert screen.verdict_rule([_row() for _ in range(6)]) == "DESIGN_PASS"


def test_verdict_any_judged_failure_is_failed_screen():
    rows = [_row() for _ in range(5)] + [_row(c2=False)]
    assert screen.verdict_rule(rows) == "FAILED_SCREEN"


def test_verdict_insufficient_without_failure_is_not_executable():
    rows = [_row() for _ in range(5)] + [_row(n=120)]
    assert screen.verdict_rule(rows) == "NOT_EXECUTABLE"


def test_verdict_failure_beats_insufficient():
    rows = [_row() for _ in range(4)] + [_row(c3=False), _row(n=50)]
    assert screen.verdict_rule(rows) == "FAILED_SCREEN"
