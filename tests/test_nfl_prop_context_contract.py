import pytest

from sportsedge.sports.nfl.prop_context_contract import (
    RUN_IT_SEQUENCE,
    validate_context_payload,
)


def test_nfl_prop_context_rejects_market_social_fields():
    with pytest.raises(ValueError):
        validate_context_payload({"sportsbook_price": -110})
    with pytest.raises(ValueError):
        validate_context_payload({"social_pick": "over"})


def test_nfl_prop_context_starts_outside_model_and_truth_gate():
    validate_context_payload({"model_p_eligible": False, "truth_gate_eligible": False})
    with pytest.raises(ValueError):
        validate_context_payload({"model_p_eligible": True})
    with pytest.raises(ValueError):
        validate_context_payload({"truth_gate_eligible": True})


def test_nfl_run_it_sequence_places_price_after_distribution():
    assert RUN_IT_SEQUENCE.index("distribution") < RUN_IT_SEQUENCE.index("market_price")
    assert RUN_IT_SEQUENCE.index("market_price") < RUN_IT_SEQUENCE.index("ev")
    assert RUN_IT_SEQUENCE.index("ev") < RUN_IT_SEQUENCE.index("execution_gate")
