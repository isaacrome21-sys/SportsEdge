"""Lane 2 (NFL totals): PIT-safe team scoring-rate model. Written before the model."""
import math

import pytest

from sportsedge.sports.nfl import total_scoring_model as m


def _g(season, week, home, away, hs, as_, roof="outdoors", wind=None, line=44.0):
    return {"season": season, "week": week, "gameday": f"{season}-09-{10 + week:02d}",
            "home_team": home, "away_team": away, "home_score": hs, "away_score": as_,
            "roof": roof, "wind": wind, "total_line": line}


def test_no_22_point_placeholder_and_projection_uses_past_only():
    games = [_g(2020, w, "A", "B", 40, 35) for w in range(1, 9)]
    future = _g(2020, 9, "A", "B", 0, 0)
    preds = m.walk_forward(games + [future], m.DEFAULT_PARAMS)
    p_before = preds[-1]["proj_total"]
    # changing the outcome of the game being predicted must not change its projection
    future2 = dict(future, home_score=99, away_score=99)
    assert m.walk_forward(games + [future2], m.DEFAULT_PARAMS)[-1]["proj_total"] == p_before
    # high-scoring history must lift projection above 2*22 league prior
    assert p_before > 50.0
    assert "22" not in m.MODEL_ID


def test_offense_vs_defense_direction():
    games = []
    for w in range(1, 9):
        games.append(_g(2020, w, "HI", f"X{w}", 38, 30))
        games.append(_g(2020, w, "LO", f"Y{w}", 10, 7))
    preds = m.walk_forward(games + [_g(2020, 9, "HI", "LO", 0, 0)], m.DEFAULT_PARAMS)
    p = preds[-1]
    assert p["proj_home"] > p["proj_away"]


def test_dome_and_wind_adjustments_signs():
    base = m.environment_adjustment({"roof": "outdoors", "wind": 0}, m.DEFAULT_PARAMS)
    assert m.environment_adjustment({"roof": "dome", "wind": None}, m.DEFAULT_PARAMS) >= base
    assert m.environment_adjustment({"roof": "outdoors", "wind": 25}, m.DEFAULT_PARAMS) < base


def test_over_probability_push_aware_and_bounded():
    p = m.total_probabilities(45.0, 44.0, sigma=13.0)
    assert p["p_push"] > 0 and abs(p["p_over"] + p["p_under"] + p["p_push"] - 1) < 1e-9
    h = m.total_probabilities(45.0, 44.5, sigma=13.0)
    assert h["p_push"] == 0.0 and h["p_over"] > 0.5


def test_gate_fails_closed_without_passing_backtest():
    assert m.pricing_status(None)["may_create_edges"] is False
    failing = {"brier_diff_ci95": [-0.001, 0.004], "n_test": 1300, "passes": False}
    st = m.pricing_status(failing)
    assert st["may_create_edges"] is False and st["status"].startswith("WATCH")
    # even a "passing" claim with too-small n or CI touching 0 cannot create edges
    assert m.pricing_status({"brier_diff_ci95": [-0.01, 0.0], "n_test": 1300, "passes": True})["may_create_edges"] is False
    assert m.pricing_status({"brier_diff_ci95": [-0.01, -0.001], "n_test": 100, "passes": True})["may_create_edges"] is False


def test_committed_backtest_receipt_is_research_only():
    r = m.load_backtest_receipt()
    assert r["n_test"] >= 300
    assert r["test_seasons"][0] > max(r["train_seasons"])
    if not r["passes"]:
        assert m.pricing_status(r)["may_create_edges"] is False
