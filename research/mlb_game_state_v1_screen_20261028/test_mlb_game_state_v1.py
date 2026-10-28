"""Unit tests for the MLB_GAME_STATE_V1 screen packet.

These run WITHOUT the out-of-repo data pulls: they pin the declared
configuration, the estimator's sign conventions, the PA-value identity,
the event classifier, and the weather NO_DATA handling.
"""
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mlb_game_state_v1 as m  # noqa: E402
import build_pa_dataset as bpd  # noqa: E402


def test_declared_configuration():
    # one configuration, constants declared a priori (design 5.2 leg 5)
    assert m.FOLDS == [(2022, 2023), (2023, 2024), (2024, 2025)]
    assert m.K_SHRINK == 20 and m.KS_OUTS == 150
    assert m.KB_PA == 250 and m.KP_PA == 200 and m.KU_GAMES == 40
    assert m.BOOT_SEED == 20261028 and m.BOOT_REPS == 2000
    assert m.UMP_CAP == 0.03 and m.WX_CLAMP == 0.25
    assert m.POOL_WINDOW_DAYS == 14


def test_fit_logistic_recovers_slope_sign():
    rng = np.random.default_rng(0)
    n = 4000
    diff = rng.normal(0, 0.5, n)
    X = np.column_stack([np.ones(n), diff, rng.normal(9, 1, n)])
    beta = np.array([0.1, 1.2, 0.05])
    p = 1 / (1 + np.exp(-(X @ beta)))
    y = (rng.random(n) < p).astype(float)
    fit = m.fit_logistic(X, y)
    assert fit[1] > 0.8  # differential slope recovered, correct sign


def test_pa_value_telescoping_identity():
    # sum of RE-delta values over a half-inning = runs - RE(first state)
    setup = object.__new__(m.FoldSetup)
    setup.RE = {0: 0.5}  # state 0 = empty bases, 0 outs
    seq = [
        # PA1: solo HR from empty/0-out (after-state is again empty/0-out)
        dict(inning=1, team=0, state=0, runs=1),
        # PA2: half-ending out from empty/0-out (after-state terminal)
        dict(inning=1, team=0, state=0, runs=0),
    ]
    vals = m.FoldSetup._pa_values(setup, seq)
    assert abs(vals[0] - 1.0) < 1e-9          # 1 run + RE 0.5 - RE 0.5
    assert abs(vals[1] - (-0.5)) < 1e-9       # 0 runs + 0 - RE 0.5
    assert abs(sum(vals) - (1 - 0.5)) < 1e-9  # telescopes to runs - RE(first)


def test_event_classification():
    assert bpd.outcome_class("S7") == "1B"
    assert bpd.outcome_class("D8") == "2B"
    assert bpd.outcome_class("T9") == "3B"
    assert bpd.outcome_class("HR/F89XD") == "HR"
    assert bpd.outcome_class("W") == "BB"
    assert bpd.outcome_class("HP") == "HBP"
    assert bpd.outcome_class("K") == "OUT"
    assert bpd.outcome_class("E6") == "ROE"


def test_weather_index_no_data_paths(tmp_path=None):
    # empty manifest -> every feature is None (NO_DATA -> neutral term)
    import tempfile
    d = tempfile.mkdtemp()
    wx = m.WeatherIndex(d)
    assert wx.features(1, 2024, "2024-06-01T17:05:00Z") is None
    # roof venue -> None even with a series present
    man = {"pulls": [{"venue_id": 1, "season": 2024, "roof": True,
                      "file": "w.json", "cf_bearing_deg": 0}]}
    with open(os.path.join(d, "weather_pin_manifest.json"), "w") as fh:
        json.dump(man, fh)
    with open(os.path.join(d, "w.json"), "w") as fh:
        json.dump({"hourly": {"time": ["2024-06-01T17:00"],
                              "temperature_2m_previous_day1": [70.0],
                              "wind_speed_10m_previous_day1": [5.0],
                              "wind_direction_10m_previous_day1": [180.0],
                              "precipitation_previous_day1": [0.0]}}, fh)
    wx2 = m.WeatherIndex(d)
    assert wx2.features(1, 2024, "2024-06-01T17:05:00Z") is None


def test_bootstrap_delta_deterministic_and_signed():
    rng = np.random.default_rng(1)
    rows = []
    for _ in range(300):
        y = float(rng.random() < 0.54)
        rows.append({"y": y, "p_good": 0.54 if y else 0.46,
                     "p_flat": 0.54})
    d = m.bootstrap_delta(rows, "p_good", "p_flat", reps=200, seed=7)
    assert d["delta"] < 0  # the better-calibrated key has lower Brier
    d2 = m.bootstrap_delta(rows, "p_good", "p_flat", reps=200, seed=7)
    assert d == d2  # seeded -> reproducible


def test_deciles_cover_and_bound():
    rows = [{"p_full": 0.3 + 0.4 * (i % 10) / 9.0, "y": float(i % 2)}
            for i in range(1000)]
    dec = m.deciles(rows)
    assert len(dec) == 10 and all(d["n"] == 100 for d in dec)
    assert all(0.0 <= d["dev"] <= 1.0 for d in dec)


if __name__ == "__main__":
    test_declared_configuration()
    test_fit_logistic_recovers_slope_sign()
    test_pa_value_telescoping_identity()
    test_event_classification()
    test_weather_index_no_data_paths()
    test_bootstrap_delta_deterministic_and_signed()
    test_deciles_cover_and_bound()
    print("ALL TESTS PASS")
