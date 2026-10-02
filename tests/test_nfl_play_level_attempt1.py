from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np

from scripts.run_nfl_play_level_attempt1 import (
    _calibration_logistic,
    _half_point,
    _fit_ridge,
    _predict,
    build_rows,
    starter_at,
)

EASTERN = ZoneInfo("America/New_York")


def _attempt9():
    zero = {
        "feature_mean": [0.0] * 6,
        "feature_std": [1.0] * 6,
        "coefficients": [0.0] * 6,
        "intercept": 0.0,
    }
    total = dict(zero)
    total["intercept"] = 40.0
    return {"runtime": {"targets": {"margin": zero, "total": total}}}


def _off(player: str, shift: float = 0.0):
    return {
        "epa": 0.10 + shift,
        "success": 0.45 + shift / 10,
        "pass_epa": 0.14 + shift,
        "rush_epa": 0.04 + shift,
        "pass_oe": 2.0 + shift,
        "plays": 60.0 + shift,
        "qb": {player: (30.0, 3.0 + shift, 25.0, 1.0 + shift)},
    }


def _schedule(n=8):
    start = datetime(2016, 9, 1, 20, 0, tzinfo=EASTERN)
    rows = []
    for i in range(n):
        rows.append({
            "season": 2016,
            "week": i + 1,
            "game_id": f"g{i+1}",
            "kickoff": start + timedelta(days=7 * i),
            "home": "H",
            "away": "A",
            "home_score": 24 + (i % 3),
            "away_score": 20 + (i % 2),
            "spread_line": 3.5,
            "total_line": 44.5,
        })
    return rows


def _depth():
    stamp = datetime(2016, 8, 1, 12, 0, tzinfo=EASTERN).isoformat()
    return [
        {"dt": stamp, "team": "H", "pos_abb": "QB", "pos_rank": 1, "gsis_id": "QB-H"},
        {"dt": stamp, "team": "A", "pos_abb": "QB", "pos_rank": 1, "gsis_id": "QB-A"},
    ]


def _pbp(n=8, game6_shift=0.0):
    out = {}
    for i in range(n):
        shift = game6_shift if i == 5 else 0.0
        out[f"g{i+1}"] = {"H": _off("QB-H", shift), "A": _off("QB-A", -shift)}
    return out


def test_half_point_contract():
    assert _half_point(3.5)
    assert _half_point(-7.5)
    assert not _half_point(3.0)
    assert not _half_point(None)


def test_starter_is_latest_unique_pit_snapshot():
    kickoff = datetime(2024, 10, 1, 20, 0, tzinfo=EASTERN)
    game = {"season": 2025, "week": 4, "kickoff": kickoff}
    depth = [
        {"dt": (kickoff - timedelta(days=2)).isoformat(), "team": "H", "pos_abb": "QB", "pos_rank": 1, "gsis_id": "OLD"},
        {"dt": (kickoff - timedelta(hours=2)).isoformat(), "team": "H", "pos_abb": "QB", "pos_rank": 1, "gsis_id": "NEW"},
        {"dt": (kickoff + timedelta(hours=1)).isoformat(), "team": "H", "pos_abb": "QB", "pos_rank": 1, "gsis_id": "FUTURE"},
    ]
    assert starter_at(depth, "H", game) == "NEW"
    depth.append({"dt": (kickoff - timedelta(hours=2)).isoformat(), "team": "H", "pos_abb": "QB", "pos_rank": 1, "gsis_id": "AMBIG"})
    assert starter_at(depth, "H", game) is None


def test_starter_reuses_merged_weekly_historical_depth_contract():
    kickoff = datetime(2021, 9, 19, 13, 0, tzinfo=EASTERN)
    game = {"season": 2021, "week": 2, "kickoff": kickoff}
    depth = [
        {"season": 2021, "week": 1, "club_code": "H", "game_type": "REG", "depth_team": 1, "position": "QB", "depth_position": "QB", "gsis_id": "OLD"},
        {"season": 2021, "week": 2, "club_code": "H", "game_type": "REG", "depth_team": 1, "position": "QB", "depth_position": "QB", "gsis_id": "CURRENT"},
        {"season": 2021, "week": 3, "club_code": "H", "game_type": "REG", "depth_team": 1, "position": "QB", "depth_position": "QB", "gsis_id": "FUTURE"},
    ]
    assert starter_at(depth, "H", game) == "CURRENT"


def test_target_game_pbp_cannot_enter_its_own_features():
    schedule = _schedule()
    normal = build_rows(schedule, _pbp(), _depth(), _attempt9(), {2016})
    shifted = build_rows(schedule, _pbp(game6_shift=10.0), _depth(), _attempt9(), {2016})
    n6 = next(r for r in normal if r["game_id"] == "g6")
    s6 = next(r for r in shifted if r["game_id"] == "g6")
    assert n6["x_margin"] == s6["x_margin"]
    assert n6["x_total"] == s6["x_total"]
    n7 = next(r for r in normal if r["game_id"] == "g7")
    s7 = next(r for r in shifted if r["game_id"] == "g7")
    assert n7["x_margin"] != s7["x_margin"] or n7["x_total"] != s7["x_total"]


def test_ridge_fit_is_deterministic_and_finite():
    x = np.asarray([[1.0, 2.0], [2.0, 1.0], [3.0, 0.0], [4.0, -1.0]])
    y = np.asarray([1.0, 1.5, 2.0, 2.5])
    a = _fit_ridge(x, y, 1.0)
    b = _fit_ridge(x, y, 1.0)
    assert np.allclose(a["beta"], b["beta"])
    assert np.all(np.isfinite(_predict(a, x)))


def test_logistic_calibration_recovers_near_identity_on_constructed_rates():
    ps = [0.1] * 100 + [0.3] * 100 + [0.7] * 100 + [0.9] * 100
    ys = (
        [1] * 10 + [0] * 90
        + [1] * 30 + [0] * 70
        + [1] * 70 + [0] * 30
        + [1] * 90 + [0] * 10
    )
    intercept, slope = _calibration_logistic(ps, ys)
    assert abs(intercept) < 1e-6
    assert abs(slope - 1.0) < 1e-6
