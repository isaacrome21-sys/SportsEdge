import math
import pytest

from sportsedge.mlb_edge_score import MLBEdgeScoreError, score_mlb_edge


def test_push_aware_integer_total_economics():
    row = score_mlb_edge(
        model_p=.50, american_odds=-110, opposite_odds=-110,
        push_probability=.10, push_possible=True,
    )
    assert row.status == "ACTIONABLE"
    assert row.p_push == .10
    assert row.p_loss == pytest.approx(.40)
    assert row.ev_per_dollar == pytest.approx(.50*(100/110)-.40)
    assert row.edge == pytest.approx(.50/.90-.50)
    assert row.fair_odds == -125
    assert "PUSH_AWARE_SETTLEMENT" in row.reason_codes


def test_push_capable_market_without_push_mass_fails_closed():
    row = score_mlb_edge(
        model_p=.50, american_odds=-110, opposite_odds=-110,
        push_possible=True,
    )
    assert row.status == "BLOCKED"
    assert row.confidence_score == 0
    assert row.reason_codes == ("PUSH_PROBABILITY_UNAVAILABLE",)


def test_binary_market_is_unchanged_when_push_is_zero():
    row = score_mlb_edge(
        model_p=.62, american_odds=-150, opposite_odds=130,
        push_probability=0.0,
    )
    assert row.ev_per_dollar == pytest.approx(.62*(100/150)-.38)
    assert row.p_push == 0.0
    assert row.p_loss == pytest.approx(.38)


def test_invalid_push_mass_and_reliability_fail_closed():
    with pytest.raises(MLBEdgeScoreError, match="MODEL_PUSH_MASS_INVALID"):
        score_mlb_edge(model_p=.60, american_odds=-110, opposite_odds=-110,
                       push_probability=.40, push_possible=True)
    with pytest.raises(MLBEdgeScoreError, match="RELIABILITY_OUT_OF_RANGE"):
        score_mlb_edge(model_p=.60, american_odds=-110, opposite_odds=-110,
                       reliability=math.nan)
