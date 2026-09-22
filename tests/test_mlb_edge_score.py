from sports.common.ev_math import american_to_decimal, devig_power
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
    assert "RAW_IMPLIED_USED" in r.reason_codes and "POWER_V1_NO_VIG" not in r.reason_codes

def test_no_vig_is_shared_power_v1_not_multiplicative():
    implied=[1/american_to_decimal(-150),1/american_to_decimal(130)]
    assert abs(binary_no_vig_probability(-150,130)-devig_power(implied)[0])<1e-12
    r=score_mlb_edge(model_p=.62,american_odds=-150,opposite_odds=130)
    assert "POWER_V1_NO_VIG" in r.reason_codes
    assert abs(r.market_p-devig_power(implied)[0])<1e-12

def test_longshot_method_sensitivity_blocks_instead_of_scoring():
    # +600/-1000: POWER ~10.5% vs MULTIPLICATIVE ~13.6%, far beyond the 1pp guard.
    r=score_mlb_edge(model_p=.20,american_odds=600,opposite_odds=-1000)
    assert r.status=="BLOCKED"
    assert r.reason_codes==("DEVIG_METHOD_SENSITIVITY",)
    assert r.confidence_score==0 and r.edge is None and r.ev_per_dollar is None

def test_context_cannot_change_score():
    a=score_mlb_edge(model_p=.60,american_odds=110,context={"capper":"A","tickets":99})
    b=score_mlb_edge(model_p=.60,american_odds=110,context={"capper":"B","tickets":1})
    assert a==b

def test_no_model_is_explicit():
    assert score_mlb_edge(model_p=None,american_odds=110).status=="NO_MODEL"
