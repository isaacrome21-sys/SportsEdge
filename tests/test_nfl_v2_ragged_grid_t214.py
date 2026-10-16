"""#2265 owner finding: ragged/non-rectangular grids with valid total mass must be refused."""
import pytest

from sportsedge.sports.nfl import unified_market_engine_v2 as v2

RAGGED = [
    [[0.5, 0.25], [0.25]],
    [[0.25, 0.25, 0.25], [0.25]],
    [[1.0], [], [0.0, 0.0]],
    [[0.5], [0.25, 0.25]],
]


@pytest.mark.parametrize("grid", RAGGED)
def test_ragged_grid_with_unit_mass_refused(grid):
    assert abs(sum(map(sum, grid)) - 1.0) < 1e-12
    with pytest.raises(v2.UnifiedNflV2GridError, match="SCORE_GRID_NOT_RECTANGULAR"):
        v2.validate_score_grid(grid)


def test_non_square_unit_mass_refused():
    with pytest.raises(v2.UnifiedNflV2GridError, match="SCORE_GRID_NOT_RECTANGULAR"):
        v2.validate_score_grid([[0.25, 0.25], [0.25, 0.25], [0.0, 0.0]])


@pytest.mark.parametrize("grid", RAGGED)
def test_ragged_grid_never_reaches_v1_sampler_or_pricer(grid, monkeypatch):
    called = []
    monkeypatch.setattr(v2._v1, "sample_score_paths", lambda *a, **k: called.append(1))
    monkeypatch.setattr(v2._v1, "price_game_market", lambda *a, **k: called.append(2))
    with pytest.raises(v2.UnifiedNflV2GridError):
        v2.sample_score_paths(grid, n_sims=10, seed=1)
    with pytest.raises(v2.UnifiedNflV2GridError):
        v2.price_game_market(grid, {"market": "moneyline"})
    assert called == []


def test_rectangular_valid_grid_still_accepted():
    v2.validate_score_grid([[0.25, 0.25], [0.25, 0.25]])
