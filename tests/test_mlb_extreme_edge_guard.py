from sportsedge.mlb_edge_score import MLB_EDGE_SCORE_PROVENANCE
from sportsedge.mlb_scored_card import (
    EXTREME_EDGE_REASON,
    MAX_UNCONFIRMED_EDGE,
    build_mlb_scored_card,
    top_mlb_edges,
)


def _row(edge: float):
    market_p = 0.50
    model_p = market_p + edge
    return {
        "market": "TOTALS",
        "scored_status": "ACTIONABLE",
        "confidence_score": 90,
        "model_p": model_p,
        "market_p": market_p,
        "edge": edge,
        "ev_per_dollar": 0.10,
        "reason_codes": ("POWER_V1_NO_VIG",),
        "confidence_provenance": MLB_EDGE_SCORE_PROVENANCE,
    }


def test_fifteen_point_gap_is_not_printed_as_normal_actionable_play():
    card = build_mlb_scored_card([_row(0.15)])
    assert card[0]["scored_status"] == "PASS"
    assert card[0]["extreme_edge_needs_confirm"] is True
    assert EXTREME_EDGE_REASON in card[0]["presentation_reason_codes"]
    assert top_mlb_edges([_row(0.15)]) == []


def test_edge_below_sanity_threshold_remains_eligible():
    edge = MAX_UNCONFIRMED_EDGE - 0.001
    card = build_mlb_scored_card([_row(edge)])
    assert card[0]["scored_status"] == "ACTIONABLE"
    assert card[0]["extreme_edge_needs_confirm"] is False


def test_threshold_itself_fails_closed_for_confirmation():
    card = build_mlb_scored_card([_row(MAX_UNCONFIRMED_EDGE)])
    assert card[0]["scored_status"] == "PASS"
    assert EXTREME_EDGE_REASON in card[0]["presentation_reason_codes"]
