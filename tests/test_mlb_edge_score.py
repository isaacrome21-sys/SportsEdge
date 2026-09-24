from sports.common.ev_math import american_to_decimal, devig_power
from sportsedge.mlb_edge_score import score_mlb_edge, fair_american_odds, binary_no_vig_probability, ev_per_dollar

def test_score_bounded_and_stronger_edge_monotonic():
    low=score_mlb_edge(model_p=.55,american_odds=-110,opposite_odds=-110)
    high=score_mlb_edge(model_p=.62,american_odds=-110,opposite_odds=-110)
    assert 0 <= low.confidence_score < high.confidence_score <= 100

def test_stale_quote_blocks():
    r=score_mlb_edge(model_p=.60,american_odds=120,opposite_odds=-140,quote_age_seconds=301,quote_ttl_seconds=300)
    assert r.status=="BLOCKED" and "STALE_QUOTE" in r.reason_codes

def test_default_quote_ttl_is_180_seconds():
    fresh=score_mlb_edge(model_p=.60,american_odds=120,opposite_odds=-140,quote_age_seconds=180)
    stale=score_mlb_edge(model_p=.60,american_odds=120,opposite_odds=-140,quote_age_seconds=181)
    assert fresh.status=="ACTIONABLE"
    assert stale.status=="BLOCKED" and stale.reason_codes==("STALE_QUOTE",)

def test_missing_required_input_blocks():
    assert score_mlb_edge(model_p=.60,american_odds=120,opposite_odds=-140,inputs_complete=False).status=="BLOCKED"

def test_plus_and_minus_fair_odds():
    assert fair_american_odds(.40)==150
    assert fair_american_odds(.60)==-150

def test_binary_no_vig_symmetric_pair_is_half():
    assert abs(binary_no_vig_probability(-110,-110)-.5)<1e-12

def test_one_sided_quote_is_refused_not_scored():
    r=score_mlb_edge(model_p=.70,american_odds=120)
    assert r.status=="BLOCKED"
    assert r.reason_codes==("OPPOSITE_QUOTE_UNAVAILABLE",)
    assert r.confidence_score==0 and r.market_p is None and r.edge is None and r.ev_per_dollar is None

def test_n_way_market_blocks_even_with_opposite_price():
    r=score_mlb_edge(model_p=.25,american_odds=400,opposite_odds=-500,n_way_market=True)
    assert r.status=="BLOCKED"
    assert r.reason_codes==("N_WAY_DEVIG_UNFROZEN",)
    assert r.confidence_score==0 and r.market_p is None

def test_no_vig_is_shared_power_v1_not_multiplicative():
    implied=[1/american_to_decimal(-150),1/american_to_decimal(130)]
    assert abs(binary_no_vig_probability(-150,130)-devig_power(implied)[0])<1e-12
    r=score_mlb_edge(model_p=.62,american_odds=-150,opposite_odds=130)
    assert "POWER_V1_NO_VIG" in r.reason_codes
    assert abs(r.market_p-devig_power(implied)[0])<1e-12

def test_longshot_method_sensitivity_blocks_instead_of_scoring():
    r=score_mlb_edge(model_p=.20,american_odds=600,opposite_odds=-1000)
    assert r.status=="BLOCKED"
    assert r.reason_codes==("DEVIG_METHOD_SENSITIVITY",)
    assert r.confidence_score==0 and r.edge is None and r.ev_per_dollar is None

def test_context_cannot_change_score():
    a=score_mlb_edge(model_p=.60,american_odds=110,opposite_odds=-130,context={"capper":"A","tickets":99})
    b=score_mlb_edge(model_p=.60,american_odds=110,opposite_odds=-130,context={"capper":"B","tickets":1})
    assert a.status=="ACTIONABLE"
    assert a.confidence_score==b.confidence_score and a.ev_per_dollar==b.ev_per_dollar

def test_no_model_is_explicit():
    assert score_mlb_edge(model_p=None,american_odds=110).status=="NO_MODEL"

def test_zero_reliability_stays_zero_and_is_not_actionable():
    r=score_mlb_edge(estimate_p=.62,american_odds=-110,opposite_odds=-110,reliability=0.0)
    assert r.confidence_score==0
    assert r.status=="PASS"
    assert r.estimate_p==.62

def test_push_mass_reduces_ev_instead_of_treating_push_as_a_loss():
    no_push=ev_per_dollar(.60,-110,push_p=0.0)
    with_push=ev_per_dollar(.60,-110,push_p=0.20)
    assert with_push > no_push  # 20% was previously counted as a loss
    assert with_push == ev_per_dollar(.60,-110,push_p=0.20)

def test_card_labels_estimate_p_and_keeps_unofficial_footer():
    r=score_mlb_edge(estimate_p=.58,american_odds=-110,opposite_odds=-110)
    assert r.estimate_p==.58
    assert "ESTIMATE_P_UNOFFICIAL" in r.reason_codes
    assert "NOT Model_P" in r.authority_footer
