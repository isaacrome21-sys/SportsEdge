"""Unit tests for the CFB_TEAM_TOTAL_EPA_PROFILE_V2 screen runner.

Synthetic data only — no pinned inputs are read. Run from the repo root:
  python -m pytest research/cfb_team_totals_epa_profile_screen_20261028/test_screen.py -q
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_screen as rs  # noqa: E402


# ---------------------------------------------------------------- shrinkage
def test_shrink_rate_v1_discipline():
    # w = n/(n+3); n=3 -> w=0.5 halfway between observed mean and pool
    assert rs.shrink_rate(30.0, 3, 20.0) == pytest.approx(0.5 * 10 + 0.5 * 20)
    assert rs.shrink_rate(0.0, 0, 7.5) == 7.5  # no games -> pool
    assert rs.shrink_rate(90.0, 9, 0.0) == pytest.approx(0.75 * 10)


# ------------------------------------------------------------------- success
def test_success_rule_thresholds():
    df = pd.DataFrame({
        "down": [1.0, 2.0, 3.0, 4.0, 1.0, np.nan],
        "distance": [10.0, 10.0, 10.0, 5.0, 10.0, 10.0],
        "yards": [5.0, 6.9, 10.0, 4.0, 4.9, 20.0],
    })
    s = rs.success_value(df)
    assert s.iloc[0] == 1.0   # 1st & 10, gained exactly 50%
    assert s.iloc[1] == 0.0   # 2nd & 10, 6.9 < 70%
    assert s.iloc[2] == 1.0   # 3rd & 10, full distance
    assert s.iloc[3] == 0.0   # 4th & 5, 4 < 5
    assert s.iloc[4] == 0.0   # 1st & 10, 4.9 < 5
    assert np.isnan(s.iloc[5])  # undefined inputs -> undefined


# ------------------------------------------------------------- drive facts
def _toy_plays():
    # one game, team A: drive 1 reaches the 15 and scores a TD;
    # drive 2 stalls at midfield (min ytg 50) and punts.
    rows = []
    for seq, (drv, ytg, res) in enumerate([
            (1, 80, "TD"), (1, 40, "TD"), (1, 15, "TD"),
            (2, 70, "PUNT"), (2, 50, "PUNT")]):
        rows.append({"game_id": 1, "pos_team": "A", "drive_key": drv,
                     "play_seq": seq, "passer": "QB A", "epa": 0.5,
                     "is_pass": True, "is_rush": False, "down": 1.0,
                     "distance": 10.0, "yards": 5.0, "ytg": float(ytg),
                     "drive_result": res})
    return pd.DataFrame(rows)


def test_drive_aggregation_eckel_rz_points():
    agg = rs.aggregate_game_plays(_toy_plays())
    assert len(agg) == 1
    r = agg.iloc[0]
    assert r["drives"] == 2
    assert r["eckel_n"] == 1        # only drive 1 got inside the 40
    assert r["eckel_pts"] == 7.0    # ... and scored a TD on it
    assert r["rz_n"] == 1           # ... and inside the 20
    assert r["rz_td_n"] == 1
    assert r["qb_first"] == "QB A"
    assert r["epa_n"] == 5 and r["epa_sum"] == pytest.approx(2.5)


# --------------------------------------------------------------------- ridge
def test_ridge_recovers_signal_and_shrinks():
    rng = np.random.default_rng(7)
    n = 400
    X = rng.normal(size=(n, len(rs.FEATURES)))
    y = 2.0 + 1.5 * X[:, 0] - 0.5 * X[:, 5] + rng.normal(scale=0.1, size=n)
    train = pd.DataFrame(X, columns=rs.FEATURES)
    train["ppd_actual"] = y
    m = rs.fit_ridge(train)
    assert m["coef_raw"][0] == pytest.approx(1.5, abs=0.15)
    assert m["coef_raw"][5] == pytest.approx(-0.5, abs=0.15)
    # the unpenalized intercept is the training mean of y, by construction
    assert m["y_mean"] == pytest.approx(float(np.mean(y)), abs=0.02)
    pred = rs.predict_ppd(m, train)
    assert np.corrcoef(pred, y)[0, 1] > 0.99


def test_ridge_lambda_is_the_declared_constant():
    assert rs.RIDGE_LAMBDA == 1.0
    assert rs.POOL_K == 3.0


# ---------------------------------------------------------------- continuity
def test_passer_sequences_continuity_and_stratum():
    tg = pd.DataFrame([
        # (season, week, game, team, passer): team T passers by game:
        # g1 Q1, g2 Q1, g3 Q2, g4 Q2 -> continuity at g3 compares the
        # two priors (g2 Q1 vs g1 Q1) = 1; at g4 (Q2 vs Q1) = 0.
        {"season": 2023, "week": w, "game_id": g, "team": "T",
         "team_key": "t", "opponent": "U", "qb_first": q}
        for w, g, q in [(1, 11, "Q1"), (2, 12, "Q1"), (3, 13, "Q2"),
                        (4, 14, "Q2")]
    ])
    out = rs._passer_sequences(tg)
    by_game = {int(r.game_id): r for r in out.itertuples()}
    assert np.isnan(by_game[11].cont_raw)   # no priors
    assert np.isnan(by_game[12].cont_raw)   # one prior only
    assert by_game[13].cont_raw == 1.0      # Q1 followed Q1
    assert by_game[14].cont_raw == 0.0      # Q2 followed Q1
    assert by_game[13].qb_changed is True or by_game[13].qb_changed == True  # noqa: E712
    assert not by_game[12].qb_changed


# ------------------------------------------------------------- implied split
def test_implied_split_identity():
    # S_close = -home_team_spread; implied_home + implied_away = T and
    # implied_home - implied_away = S_close.
    spread, total = -7.0, 55.0
    s_close = -spread
    ih, ia = (total + s_close) / 2, (total - s_close) / 2
    assert ih + ia == total and ih - ia == s_close == 7.0


# --------------------------------------------------------------- NB interval
def test_nb_interval_orders_and_covers_center():
    from scipy import stats
    r, mu = 5.0, 28.0
    p = r / (r + mu)
    lo = stats.nbinom.ppf(0.10, r, p)
    hi = stats.nbinom.ppf(0.90, r, p)
    assert lo < mu < hi


# ------------------------------------------------------------- registry gate
def test_illinois_names_come_from_registry_source():
    assert "illinois" in rs.IL_COLLEGE_NAMES
    assert "northwestern" in rs.IL_COLLEGE_NAMES
    assert len(rs.IL_COLLEGE_NAMES) == 21
    assert rs.norm("Northern Illinois") in rs.IL_COLLEGE_NAMES


# ------------------------------------------------------- 2021 dialect (R9)
def test_idstr_canonicalizes_espn_ids():
    assert rs._idstr(2390) == "2390"
    assert rs._idstr(2390.0) == "2390"
    assert rs._idstr("2390") == "2390"
    assert rs._idstr("Georgia") == "Georgia"  # names pass through


# ---------------------------------------------------------------- gate values
def test_cohort_gate_is_2861_run_of_record():
    assert rs.EXPECTED["cohort_games"] == 1586
    assert rs.EXPECTED["cohort_rows"] == 3172
    assert rs.EXPECTED["games_per_season"] == {2023: 512, 2024: 532,
                                               2025: 542}
