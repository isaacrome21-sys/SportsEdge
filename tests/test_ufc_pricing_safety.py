import pytest

from sportsedge.ufc_engine import (
    american_to_implied,
    expected_value,
    fair_american,
    no_vig_two_way,
    truth_gate,
)


@pytest.mark.parametrize("odds", [0, 99, -99, True, float("inf")])
def test_ufc_rejects_invalid_american_odds(odds):
    with pytest.raises(ValueError, match="UFC_ODDS_INVALID"):
        american_to_implied(odds)


def test_ufc_two_way_devig_matches_even_market():
    a, b = no_vig_two_way(-110, -110)
    assert a == pytest.approx(0.5)
    assert b == pytest.approx(0.5)


@pytest.mark.parametrize("prob", [-0.01, 1.01, True, float("nan")])
def test_ufc_expected_value_rejects_bad_probability(prob):
    with pytest.raises(ValueError, match="prob"):
        expected_value(prob, -110)


@pytest.mark.parametrize("prob", [0.0, 1.0, True, float("nan")])
def test_ufc_fair_american_requires_open_probability(prob):
    with pytest.raises(ValueError, match="prob"):
        fair_american(prob)


def test_ufc_truth_gate_rejects_bad_market_probability():
    with pytest.raises(ValueError, match="market_novig"):
        truth_gate(prob=0.60, odds=-110, market_novig=1.2, uncertainty=0.10)


def test_ufc_truth_gate_preserves_normal_pass_semantics():
    out = truth_gate(
        prob=0.60,
        odds=110,
        market_novig=0.54,
        uncertainty=0.10,
        min_edge=0.025,
        min_ev=0.03,
        max_uncertainty=0.20,
    )
    assert out["pass"] is True
    assert out["edge"] == pytest.approx(0.06)
