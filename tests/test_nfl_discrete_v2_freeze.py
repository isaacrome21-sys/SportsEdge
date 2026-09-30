from sportsedge.sports.nfl.discrete_v2 import (
    FAMILY,
    load_freeze,
    margin_mass,
    means_from_attempt9,
    score_grid,
    tie_mass,
)
from sportsedge.sports.nfl.discrete_v2_eval import evaluate_holdout, load_eval_freeze
from sportsedge.sports.nfl.discrete_v2_fit import SNAPSHOT, build_freeze, snapshot_sha256


def test_fit_rebuilds_freeze_sha() -> None:
    rebuilt = build_freeze()
    on_disk = load_freeze()
    assert rebuilt["artifact_sha256"] == on_disk["artifact_sha256"]
    assert on_disk["fit_window"]["source_sha256"] == snapshot_sha256(SNAPSHOT)
    assert on_disk["family"] == FAMILY
    assert on_disk["authority"]["phone_card"] is False


def test_grid_matches_fit_window_baselines() -> None:
    art = load_freeze()
    loc = art["shape"]["lift_fit_location"]
    base = art["fit_window_baselines"]
    grid = score_grid(loc["mean_home_score"], loc["mean_away_score"], art)
    assert abs(sum(sum(row) for row in grid) - 1.0) < 1e-9
    assert abs(margin_mass(grid, 3) - base["p_abs_margin_3"]) < 0.005
    assert abs(margin_mass(grid, 7) - base["p_abs_margin_7"]) < 0.005
    assert abs(tie_mass(grid) - base["tie_rate"]) < 0.002


def test_attempt9_mapping_locked() -> None:
    means = means_from_attempt9(3.0, 44.5)
    assert means["mean_home"] == 23.75
    assert means["mean_away"] == 20.75
    ev = load_eval_freeze()
    assert ev["mapping"]["home"] == "(total + margin) / 2"
    assert ev["min_n"] == 80
    assert ev["holdout"]["weeks"] == [4, 5, 6, 7, 8, 9, 10, 11, 12]


def test_evaluator_insufficient_under_80() -> None:
    games = [
        {
            "attempt9_margin": 3.0,
            "attempt9_total": 44.5,
            "home_score": 24,
            "away_score": 21,
        }
        for _ in range(79)
    ]
    out = evaluate_holdout(games)
    assert out["status"] == "INSUFFICIENT"
    assert out["pass"] is False
    assert out["n"] == 79
