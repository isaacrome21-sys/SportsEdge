from sportsedge.mlb_edge_score import score_mlb_edge, fair_american_odds, binary_no_vig_probability

def test_score_bounded_and_stronger_edge_monotonic():
    low=score_mlb_edge(model_p=.55,american_odds=-110,opposite_odds=-110)
    high=score_mlb_edge(model_p=.62,american_odds=-110,opposite_odds=-110)
    assert 0 <= low.confidence_score < high.confidence_score <= 100

def test_stale_quote_blocks():
    r=score_mlb_edge(model_p=.60,american_odds=120,quote_age_seconds=301,quote_ttl_seconds=300)
    assert r.status=="BLOCKED" and "STALE_QUOTE" in r.reason_codes

def test_missing_required_input_blocks():
    assert score_mlb_edge(model_p=.60,american_odds=120,inputs_complete=False).status=="BLOCKED"

def test_plus_and_minus_fair_odds():
    assert fair_american_odds(.40)==150
    assert fair_american_odds(.60)==-150

def test_binary_no_vig_and_nway_not_binary_normalized():
    assert abs(binary_no_vig_probability(-110,-110)-.5)<1e-12
    r=score_mlb_edge(model_p=.25,american_odds=400,opposite_odds=-500,n_way_market=True)
    assert "RAW_IMPLIED_USED" in r.reason_codes and "BINARY_NO_VIG" not in r.reason_codes

def test_context_cannot_change_score():
    a=score_mlb_edge(model_p=.60,american_odds=110,context={"capper":"A","tickets":99})
    b=score_mlb_edge(model_p=.60,american_odds=110,context={"capper":"B","tickets":1})
    assert a==b

def test_no_model_is_explicit():
    assert score_mlb_edge(model_p=None,american_odds=110).status=="NO_MODEL"
