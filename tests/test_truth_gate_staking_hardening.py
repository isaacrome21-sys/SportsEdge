import pytest

from sportsedge.truth_gate import TruthGateError, decide_bet


def _decision(**overrides):
    kwargs = dict(
        model_p=0.90,
        american_odds=200,
        fair_market_probability=0.50,
        bound=True,
        fresh=True,
        deployed=True,
        edge_floor=0.01,
    )
    kwargs.update(overrides)
    return decide_bet(**kwargs)


def test_default_truth_gate_never_recommends_more_than_full_bankroll():
    decision = _decision(kelly_multiplier=100.0)
    assert decision.bet_status == "OFFICIAL_BET"
    assert decision.kelly_fraction == 1.0


def test_explicit_kelly_cap_is_enforced():
    decision = _decision(kelly_multiplier=1.0, max_kelly_fraction=0.05)
    assert decision.kelly_fraction == pytest.approx(0.05)


@pytest.mark.parametrize("value", [True, False])
def test_boolean_kelly_multiplier_is_rejected(value):
    with pytest.raises(TruthGateError, match="kelly_multiplier"):
        _decision(kelly_multiplier=value)


@pytest.mark.parametrize("value", [-0.01, 1.01, True, float("inf")])
def test_invalid_kelly_cap_fails_closed(value):
    with pytest.raises(TruthGateError, match="max_kelly_fraction"):
        _decision(max_kelly_fraction=value)


def test_normal_quarter_kelly_behavior_is_unchanged_by_default_cap():
    uncapped_expected = ((2.0 * 0.90 - 0.10) / 2.0) * 0.25
    decision = _decision(kelly_multiplier=0.25)
    assert decision.kelly_fraction == pytest.approx(uncapped_expected)
