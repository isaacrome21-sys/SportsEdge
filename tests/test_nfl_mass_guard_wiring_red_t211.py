"""RED (t211u): the joint-score mass guard (03351c24) is enforced by its
consumers instead of being silently renormalised.

unified_market_engine.py is byte-locked by the NFL market-context prop V1
forward lock, so it is NOT edited; consumers outside the lock call guarded
wrappers (sampler, game pricer) and the market-anchored residual factory
validates its grids."""
import pytest

from sportsedge.sports.nfl.discrete_v2 import load_freeze, score_grid
from sportsedge.sports.nfl.score_grid_integrity import ScoreGridIntegrityError
from sportsedge.sports.nfl.score_grid_integrity import (
    guarded_price_game_market as price_game_market,
    guarded_sample_score_paths as sample_score_paths)


def _grid():
    return score_grid(23.0, 21.0, load_freeze())


def _scaled(f):
    return [[p * f for p in row] for row in _grid()]


@pytest.mark.parametrize("bad", [
    lambda: _scaled(0.9), lambda: _scaled(1.1),
    lambda: [[float("nan")] + r[1:] for r in _grid()],
    lambda: [r[:-1] if i == 3 else r for i, r in enumerate(_grid())],
])
def test_sampler_refuses_bad_mass_instead_of_rewriting_cdf(bad):
    with pytest.raises(ScoreGridIntegrityError):
        sample_score_paths(bad(), n_sims=16, seed=1)


def test_pricer_refuses_bad_mass():
    with pytest.raises(ScoreGridIntegrityError):
        price_game_market(_scaled(0.9), {"market": "moneyline", "selection": "home"})


def test_valid_grid_still_samples_and_prices():
    assert len(sample_score_paths(_grid(), n_sims=16, seed=1)) == 16
    price_game_market(_grid(), {"market": "moneyline", "selection": "home"})


def test_market_anchored_factory_output_is_validated():
    from sportsedge.sports.nfl.market_anchored_residual import price_game
    from test_nfl_market_anchored_residual import NOW, game
    bad = lambda home, away: _scaled(0.9)
    with pytest.raises(ScoreGridIntegrityError):
        price_game(game(), raw_model_margin=3.5, raw_model_total=50.5,
                   as_of=NOW, score_grid_factory=bad)


def test_residual_unified_run_it_uses_guarded_sampler():
    import sportsedge.sports.nfl.residual_unified_run_it as rur
    assert rur.guarded_sample_score_paths is sample_score_paths
    assert not hasattr(rur, "sample_score_paths") or \
        "guarded_sample_score_paths(grid" in open(rur.__file__).read()
