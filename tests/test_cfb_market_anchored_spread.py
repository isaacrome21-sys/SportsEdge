import pytest

from sportsedge.sports.cfb.market_anchored_spread import (
    CFBMarketAnchoredSpreadError,
    adjusted_home_margin,
    fit_market_anchored_spread,
    forward_track_eligible,
    load_frozen_fit,
)


def _fixture(n=1000):
    predictions = {}
    lines = {}
    for i in range(n):
        x = (i % 21) - 10
        market_margin = float((i % 13) - 6)
        model_margin = market_margin + x
        actual_residual = 1.25 + 0.2 * x
        actual_margin = market_margin + actual_residual
        gid = str(i)
        predictions[gid] = {
            "season": 2016 + (i % 10),
            "home_pred": model_margin,
            "away_pred": 0.0,
            "home_pts": actual_margin,
            "away_pts": 0.0,
        }
        lines[gid] = {"spread": -market_margin}
    return predictions, lines


def test_fit_recovers_frozen_linear_form():
    predictions, lines = _fixture()
    fit = fit_market_anchored_spread(predictions, lines)
    assert fit.n == 1000
    assert fit.season_start == 2016
    assert fit.season_end == 2025
    assert fit.intercept == pytest.approx(1.25, abs=1e-12)
    assert fit.weight == pytest.approx(0.2, abs=1e-12)


def test_adjusted_margin_is_market_plus_residual_overlay():
    out = adjusted_home_margin(
        raw_model_home_margin=7.0,
        market_home_margin=3.0,
        intercept=-0.1,
        weight=0.25,
    )
    assert out == pytest.approx(3.9)


def test_forward_threshold_is_frozen_at_half_point():
    assert forward_track_eligible(adjusted_margin=3.5, market_home_margin=3.0)
    assert not forward_track_eligible(adjusted_margin=3.499, market_home_margin=3.0)


def test_fit_rejects_small_join():
    predictions, lines = _fixture(999)
    with pytest.raises(CFBMarketAnchoredSpreadError, match="ROWS_INSUFFICIENT"):
        fit_market_anchored_spread(predictions, lines)


def test_frozen_fit_binds_exact_development_output():
    fit = load_frozen_fit()
    assert fit["status"] == "FROZEN_FORWARD_TRACKING_READY"
    assert fit["n"] == 6498
    assert fit["intercept"] == pytest.approx(-0.036762711059469516)
    assert fit["weight"] == pytest.approx(-0.03317410378163576)
    assert fit["totals_enabled"] is False
    assert fit["authority"]["model_p"] is False
