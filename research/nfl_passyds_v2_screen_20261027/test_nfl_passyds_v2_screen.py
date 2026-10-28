"""Passing-yards v2 forward screen tests (construction F, draft prereg
research/grok_nfl_passyds_v2_20261022 @ 7d6431ff816c).

Run: python3 -m pytest research/nfl_passyds_v2_screen_20261027/test_nfl_passyds_v2_screen.py
"""
from __future__ import annotations

import csv
import gzip
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import score_nfl_passyds_v2_screen as scr  # noqa: E402

EV = scr.load_evaluator()


def row(week, pid, y, mu):
    return {"season": 2026, "week": week, "pid": pid, "y": float(y), "mu_v1": float(mu)}


def block_rows(weeks, per_week, y, mu, pid_prefix="QB"):
    return [row(w, f"{pid_prefix}{i}", y, mu) for w in weeks for i in range(per_week)]


# ---------- construction F: the ratio ----------

def test_ratio_shrinkage_exact_k200():
    pool = [row(4, f"Q{i}", y, 250.0) for i, y in enumerate((220.0, 230.0, 240.0, 210.0))]
    # sum_y = 900, sum_mu = 1000, mbar = 250 -> (900 + 200*250) / (1000 + 200*250)
    assert scr.correction_ratio(pool) == pytest.approx(50900.0 / 51000.0)


def test_ratio_no_pool_rows_is_one():
    assert scr.correction_ratio([]) == 1.0


def test_ratio_uses_weeks_4plus_strictly_before_the_game():
    rows = [row(3, "A", 100.0, 400.0),    # week 3: below the weeks-4+ pool floor
            row(4, "B", 230.0, 250.0),
            row(7, "C", 230.0, 250.0),
            row(8, "D", 999.0, 999.0),    # the game week itself: excluded
            row(9, "E", 999.0, 999.0)]    # later week: excluded
    expected = scr.correction_ratio([rows[1], rows[2]])
    assert scr.ratio_for_week(rows, 8) == pytest.approx(expected)
    assert scr.ratio_for_week(rows, 8) < 1.0  # the 999s would swamp it if leaked


def test_frozen_constants_match_the_draft():
    assert scr.K_SHRINKAGE == 200.0
    assert scr.CV_FROZEN == 0.3496
    assert scr.WINDOW_FIRST_WEEK == 8 and scr.WINDOW_WEEKS == 4


# ---------- the verdict rule (draft section 4), branch by branch ----------

def test_decide_verdict_branches():
    assert scr.decide_verdict(-0.2, -0.05, 9.0, 4.0, True) == "PASS_SCREEN"
    assert scr.decide_verdict(0.1, -0.05, 9.0, 4.0, True) == "FAILED_SCREEN"   # mean
    assert scr.decide_verdict(-0.2, 0.05, 9.0, 4.0, True) == "FAILED_SCREEN"   # CI hi
    assert scr.decide_verdict(-0.2, -0.05, 9.0, 9.5, True) == "FAILED_SCREEN"  # bias
    assert scr.decide_verdict(-0.2, -0.05, 9.0, 4.0, False) == "SCREEN_INCOMPLETE"


# ---------- full screen on sample rows: PASS and FAIL ----------

def test_screen_passes_when_inseason_correction_fixes_overprediction():
    pool = block_rows(range(4, 8), 6, y=232.0, mu=260.0)       # v1 +28 bias in-season
    scored = block_rows(range(8, 12), 6, y=232.0, mu=260.0)    # same bias in window
    res = scr.score_screen(EV, pool + scored)
    assert res["window_complete"] is True
    assert res["n_scored"] == 24
    assert res["mean_dcrps"] < 0
    assert res["ci95_hi"] < 0
    assert abs(res["bias_v2"]) < abs(res["bias_v1"])
    assert res["verdict"] == "PASS_SCREEN"
    # the correction is per-week and in-season: every ratio sits below 1
    assert all(r["ratio"] < 1.0 for r in res["rows"])


def test_screen_fails_when_correction_direction_reverses():
    pool = block_rows(range(4, 8), 6, y=262.0, mu=230.0)       # v1 underpredicts early
    scored = block_rows(range(8, 12), 6, y=232.0, mu=260.0)    # but overpredicts late
    res = scr.score_screen(EV, pool + scored)
    assert res["window_complete"] is True
    assert res["mean_dcrps"] > 0
    assert abs(res["bias_v2"]) > abs(res["bias_v1"])
    assert res["verdict"] == "FAILED_SCREEN"


def test_screen_incomplete_before_four_full_weeks():
    pool = block_rows(range(4, 8), 6, y=232.0, mu=260.0)
    scored = block_rows(range(8, 11), 6, y=232.0, mu=260.0)    # weeks 8-10 only
    res = scr.score_screen(EV, pool + scored)
    assert res["mean_dcrps"] < 0          # stats are reported...
    assert res["verdict"] == "SCREEN_INCOMPLETE"  # ...but no verdict is issued


def test_stopping_rule_excludes_week_12_and_later():
    pool = block_rows(range(4, 8), 6, y=232.0, mu=260.0)
    scored = block_rows(range(8, 12), 6, y=232.0, mu=260.0)
    late = block_rows([12, 13], 6, y=0.0, mu=650.0)            # would wreck the stats
    base = scr.score_screen(EV, pool + scored)
    with_late = scr.score_screen(EV, pool + scored + late)
    assert with_late["n_scored"] == base["n_scored"] == 24
    assert with_late["n_out_of_window"] == 12
    assert with_late["mean_dcrps"] == base["mean_dcrps"]
    assert with_late["verdict"] == base["verdict"] == "PASS_SCREEN"


# ---------- end to end: v1 file layout in, verdict out ----------

def _write_weekly(path: Path, season: int, weeks, yards: float):
    cols = ["season", "week", "season_type", "player_id", "position", "attempts",
            "passing_yards", "carries", "rushing_yards", "targets", "receptions",
            "receiving_yards"]
    with gzip.open(path, "wt") as fh:
        wr = csv.DictWriter(fh, fieldnames=cols)
        wr.writeheader()
        for pid in ("QB_A", "QB_B"):
            for w in weeks:
                wr.writerow({"season": season, "week": w, "season_type": "REG",
                             "player_id": pid, "position": "QB", "attempts": 30,
                             "passing_yards": yards, "carries": 2,
                             "rushing_yards": 10, "targets": 0, "receptions": 0,
                             "receiving_yards": 0})


def test_end_to_end_on_v1_layout(tmp_path):
    _write_weekly(tmp_path / "sp_2025.csv.gz", 2025, range(1, 7), 250.0)
    _write_weekly(tmp_path / "sp_2026.csv.gz", 2026, range(1, 12), 240.0)
    res = scr.run(tmp_path, 2026)
    assert res["window_complete"] is True
    assert res["n_scored"] == 8  # 2 QBs x weeks 8-11
    assert res["verdict"] in ("PASS_SCREEN", "FAILED_SCREEN")
    assert res["data_files"]["sp_2026.csv.gz"]
    # v1 mus come from the frozen estimator: priors and in-season pool are
    # both 240, so the K=3 shrinkage lands exactly on 240
    assert all(r["mu_v1"] == pytest.approx(240.0) for r in res["rows"])
