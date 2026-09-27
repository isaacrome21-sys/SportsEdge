from sportsedge.mlb_edge_score import MLB_EDGE_SCORE_PROVENANCE
from sportsedge.mlb_scored_card import build_mlb_scored_card, top_mlb_edges


def _verified_row(*, market, score, model_p, market_p, ev):
    return {
        "market": market,
        "scored_status": "ACTIONABLE",
        "confidence_score": score,
        "model_p": model_p,
        "market_p": market_p,
        "edge": model_p-market_p,
        "ev_per_dollar": ev,
        "reason_codes": ("POWER_V1_NO_VIG",),
        "confidence_provenance": MLB_EDGE_SCORE_PROVENANCE,
    }


def test_card_orders_actionable_by_confidence():
    rows=[
      _verified_row(market="HITS",score=62,model_p=.55,market_p=.51,ev=.08),
      _verified_row(market="MONEYLINE",score=81,model_p=.58,market_p=.52,ev=.11),
      {"market":"NRFI","scored_status":"BLOCKED","confidence_score":0,"edge":None,"ev_per_dollar":None},
    ]
    card=build_mlb_scored_card(rows)
    assert [x["market"] for x in card]==["MONEYLINE","HITS","NRFI"]
    assert card[0]["star_rating"]==5 and card[-1]["star_rating"]==0
    assert card[0]["confidence_verified"] is True


def test_top_edges_never_promotes_pass_or_blocked():
    rows=[
      {"market":"HR","scored_status":"PASS","confidence_score":90,"edge":-.01,"ev_per_dollar":-.02},
      _verified_row(market="TOTAL_BASES",score=55,model_p=.54,market_p=.51,ev=.05),
    ]
    assert [x["market"] for x in top_mlb_edges(rows)]==["TOTAL_BASES"]


def test_unverified_actionable_score_fails_closed_from_top_edges():
    row={
        "market":"MONEYLINE",
        "scored_status":"ACTIONABLE",
        "confidence_score":94,
        "edge":.08,
        "ev_per_dollar":.15,
    }
    assert top_mlb_edges([row]) == []
    card=build_mlb_scored_card([row])
    assert card[0]["scored_status"]=="PASS"
    assert card[0]["confidence_verified"] is False
    assert card[0]["star_rating"]==0
    assert "UNVERIFIED_CONFIDENCE_PROVENANCE" in card[0]["presentation_reason_codes"]


def test_provenance_literal_cannot_bypass_missing_probability_evidence():
    row={
        "market":"MONEYLINE",
        "scored_status":"ACTIONABLE",
        "confidence_score":90,
        "confidence_provenance":MLB_EDGE_SCORE_PROVENANCE,
        "edge":.06,
        "ev_per_dollar":.10,
        "reason_codes":("POWER_V1_NO_VIG",),
    }
    assert top_mlb_edges([row]) == []
