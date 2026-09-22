from sportsedge.mlb_scored_card import build_mlb_scored_card, top_mlb_edges

def test_card_orders_actionable_by_confidence():
    rows=[
      {"market":"HITS","scored_status":"ACTIONABLE","confidence_score":62,"edge":.04,"ev_per_dollar":.08},
      {"market":"MONEYLINE","scored_status":"ACTIONABLE","confidence_score":81,"edge":.06,"ev_per_dollar":.11},
      {"market":"NRFI","scored_status":"BLOCKED","confidence_score":0,"edge":None,"ev_per_dollar":None},
    ]
    card=build_mlb_scored_card(rows)
    assert [x["market"] for x in card]==["MONEYLINE","HITS","NRFI"]
    assert card[0]["star_rating"]==5 and card[-1]["star_rating"]==0

def test_top_edges_never_promotes_pass_or_blocked():
    rows=[
      {"market":"HR","scored_status":"PASS","confidence_score":90,"edge":-.01,"ev_per_dollar":-.02},
      {"market":"TOTAL_BASES","scored_status":"ACTIONABLE","confidence_score":55,"edge":.03,"ev_per_dollar":.05},
    ]
    assert [x["market"] for x in top_mlb_edges(rows)]==["TOTAL_BASES"]
