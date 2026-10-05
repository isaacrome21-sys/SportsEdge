import pytest

from sportsedge.sports.nfl.v2k_attempt5_serving import (
    Attempt5ServingError,
    centers_from_market,
)


def _result(verdict="ATTEMPT5_PASS"):
    return {
        "schema": "NFL_V2K_ATTEMPT5_DEVELOPMENT_VALIDATION_V1",
        "verdict": verdict,
        "attempt_consumed": True,
        "development_budget_exhausted_after_run": True,
        "live_parameters": {
            "spread_intercept": 0.0,
            "spread_line_beta": 0.0,
            "total_intercept": 0.0,
            "total_line_beta": 0.0,
            "fair_spread_scale": 13.5,
            "fair_total_scale": 13.0,
        },
    }


def _market():
    return {
        "spread_line": 3.0,
        "total_line": 44.0,
        "home_spread_odds": -110,
        "away_spread_odds": -110,
        "over_odds": -110,
        "under_odds": -110,
    }


def test_identity_pass_reproduces_market_centers():
    out = centers_from_market(_result(), _market())
    assert out["fair_margin"] == pytest.approx(3.0)
    assert out["fair_total"] == pytest.approx(44.0)
    assert out["mean_home"] == pytest.approx(23.5)
    assert out["mean_away"] == pytest.approx(20.5)


def test_fail_result_cannot_serve():
    with pytest.raises(Attempt5ServingError, match="ATTEMPT5_NOT_PASSED"):
        centers_from_market(_result("ATTEMPT5_FAIL"), _market())


def test_missing_paired_price_fails_closed():
    market = _market()
    market["away_spread_odds"] = None
    with pytest.raises(Attempt5ServingError, match="NUMERIC_REQUIRED"):
        centers_from_market(_result(), market)


def test_nonidentity_parameters_move_centers():
    result = _result()
    result["live_parameters"].update({
        "spread_intercept": 0.04,
        "spread_line_beta": 0.08,
        "total_intercept": -0.04,
        "total_line_beta": 0.08,
    })
    out = centers_from_market(result, _market())
    assert out["fair_margin"] > 3.0
    assert out["fair_total"] < 44.0
