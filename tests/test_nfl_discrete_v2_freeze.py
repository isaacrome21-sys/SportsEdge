from sportsedge.sports.nfl.discrete_v2 import (
    FAMILY,
    load_freeze,
    margin_mass,
    score_grid,
)


def test_freeze_sha_and_family() -> None:
    art = load_freeze()
    assert art["family"] == FAMILY
    assert art["authority"]["phone_card"] is False
    assert art["holdout"]["min_n"] == 80
    assert art["holdout"]["if_sha_before_2026_10_01_w4_kickoff"]["weeks"][0] == 4


def test_grid_at_fit_means_has_key_mass() -> None:
    art = load_freeze()
    loc = art["shape"]["lift_fit_location"]
    grid = score_grid(loc["mean_home_score"], loc["mean_away_score"], art)
    total = sum(sum(row) for row in grid)
    assert abs(total - 1.0) < 1e-9
    assert margin_mass(grid, 3) > 0.10
    assert margin_mass(grid, 7) > 0.05
