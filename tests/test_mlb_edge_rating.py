"""Edge rating ranks picks; input quality (old Score B) is only a pass/fail gate."""
from sportsedge.mlb_edge_score import (INPUT_QUALITY_PASS, edge_strength_score,
                                       score_mlb_edge)
from sportsedge.mlb_scored_card import build_mlb_scored_card


def test_fresh_but_tiny_edge_does_not_rate_high():
    r = score_mlb_edge(model_p=0.53, american_odds=-110, opposite_odds=-110)
    assert r.confidence_score >= 95          # input quality saturates
    assert r.edge_score < 40                 # but the bet is weak


def test_bigger_edge_rates_higher():
    small = score_mlb_edge(model_p=0.53, american_odds=-110, opposite_odds=-110)
    big = score_mlb_edge(model_p=0.58, american_odds=-110, opposite_odds=-110)
    assert big.edge_score > small.edge_score


def test_failed_input_quality_is_a_gate():
    assert edge_strength_score(ev=0.10, edge=0.06, data_quality=INPUT_QUALITY_PASS - 1) == 0
    assert edge_strength_score(ev=0.10, edge=0.06, data_quality=INPUT_QUALITY_PASS) == 100


def test_non_positive_edge_rates_zero():
    assert edge_strength_score(ev=-0.01, edge=0.02, data_quality=100) == 0
    assert edge_strength_score(ev=0.02, edge=0.0, data_quality=100) == 0


def test_card_ranks_by_edge_rating_not_input_quality():
    weak = score_mlb_edge(model_p=0.535, american_odds=-110, opposite_odds=-110)
    strong = score_mlb_edge(model_p=0.60, american_odds=-110, opposite_odds=-110,
                            quote_age_seconds=30)
    card = build_mlb_scored_card([weak, strong])
    assert card[0]["edge_score"] >= card[-1]["edge_score"]
    assert all("input_quality_score" in r and "input_quality_pass" in r for r in card)


def test_failed_input_quality_cannot_be_actionable():
    stale = score_mlb_edge(model_p=0.60, american_odds=-110, opposite_odds=-110,
                           quote_age_seconds=170)
    assert stale.confidence_score < INPUT_QUALITY_PASS
    row = build_mlb_scored_card([stale])[0]
    assert row["input_quality_pass"] is False
    assert row["scored_status"] != "ACTIONABLE"
    assert row["edge_score"] == 0
