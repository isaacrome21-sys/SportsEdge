"""Synthetic regression tests only; not evidence of predictive improvement."""
import pytest
from research.mlb_batter_shrinkage_challenger import shrink_probability, chronological_compare

def test_zero_sample_reverts_to_prior():
    assert shrink_probability(0, 0, .5, 20) == .5

def test_small_sample_shrinks():
    assert .5 < shrink_probability(1, 1, .5, 20) < 1

@pytest.mark.parametrize("hits,n,prior,strength", [
    (2, 1, .5, 10), (-1, 3, .5, 10), (0, 0, 1, 10),
    (0, 0, .5, 0), (True, 1, .5, 10)])
def test_invalid_parameters_refused(hits,n,prior,strength):
    with pytest.raises(ValueError):
        shrink_probability(hits,n,prior,strength)

def test_chronological_baseline_and_no_play():
    rows = [("2026-01-01T12:00:00Z", "a", 1),
            ("2026-01-02T12:00:00Z", "a", 0)]
    result = chronological_compare(rows, prior_rate=.5, strength=20)
    assert result["n"] == 2
    assert result["market_probability_verified"] is False
    assert result["play_authorized"] is False

def test_refuses_out_of_order():
    rows = [("2026-01-02T12:00:00Z", "a", 1),
            ("2026-01-01T12:00:00Z", "a", 0)]
    with pytest.raises(ValueError, match="NON_CHRONOLOGICAL"):
        chronological_compare(rows, prior_rate=.5, strength=20)
