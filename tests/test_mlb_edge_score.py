from sports.common.ev_math import american_to_decimal, devig_power
from sportsedge.mlb_edge_score import score_mlb_edge, fair_american_odds, binary_no_vig_probability

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
    assert r.reason_codes==("POWER_V1_NO_VIG",)
    assert abs(r.market_p-devig_power(implied)[0])<1e-12

def test_longshot_method_sensitivity_blocks_instead_of_scoring():
    # +600/-1000: POWER ~10.5% vs MULTIPLICATIVE ~13.6%, far beyond the 1pp guard.
    r=score_mlb_edge(model_p=.20,american_odds=600,opposite_odds=-1000)
    assert r.status=="BLOCKED"
    assert r.reason_codes==("DEVIG_METHOD_SENSITIVITY",)
    assert r.confidence_score==0 and r.edge is None and r.ev_per_dollar is None

def test_context_cannot_change_score():
    a=score_mlb_edge(model_p=.60,american_odds=110,opposite_odds=-130,context={"capper":"A","tickets":99})
    b=score_mlb_edge(model_p=.60,american_odds=110,opposite_odds=-130,context={"capper":"B","tickets":1})
    assert a.status=="ACTIONABLE"
    assert a==b

def test_no_model_is_explicit():
    assert score_mlb_edge(model_p=None,american_odds=110).status=="NO_MODEL"

# --- commit 4/6: push-aware settlement pricing --------------------------------

def test_push_mass_flips_integer_total_from_pass_to_actionable():
    # Total 9, -110/-110. p_win .50, p_push .10, p_loss .40.
    r=score_mlb_edge(model_p=.50,american_odds=-110,opposite_odds=-110,push_probability=.10,push_possible=True)
    profit=100/110
    assert abs(r.ev_per_dollar-(.50*profit-.40))<1e-12          # push returns stake
    assert r.ev_per_dollar > 0 and r.status=="ACTIONABLE"
    assert abs((.50*profit-.50)-(-0.0454545))<1e-6             # binary treatment would be negative
    assert abs(r.edge-(.50/.90-.5))<1e-12                      # settled basis vs no-vig .5
    assert r.p_push==.10 and abs(r.p_loss-.40)<1e-12
    assert r.fair_odds==-125                                   # from settled p .5556
    assert "PUSH_AWARE_SETTLEMENT" in r.reason_codes

def test_push_math_matches_canonical_pipeline_economics():
    # Same formulas as generic_card_pipeline._candidate_economics:
    # EV = p*(dec-1) - (1-p-push); edge = p/(1-push) - fair.
    p,push=.46,.12
    r=score_mlb_edge(model_p=p,american_odds=-105,opposite_odds=-115,push_probability=push,push_possible=True)
    dec=1+100/105
    assert abs(r.ev_per_dollar-(p*(dec-1)-(1-p-push)))<1e-12
    assert abs(r.edge-(p/(1-push)-r.market_p))<1e-12

def test_team_total_push_mass_applies():
    r=score_mlb_edge(model_p=.40,american_odds=120,opposite_odds=-145,push_probability=.18,push_possible=True)
    assert abs(r.ev_per_dollar-(.40*1.2-(1-.40-.18)))<1e-12
    assert abs(r.edge-(.40/.82-r.market_p))<1e-12

def test_integer_line_without_push_mass_fails_closed():
    r=score_mlb_edge(model_p=.50,american_odds=-110,opposite_odds=-110,push_possible=True)
    assert r.status=="BLOCKED" and r.reason_codes==("PUSH_PROBABILITY_UNAVAILABLE",)
    assert r.confidence_score==0 and r.edge is None and r.ev_per_dollar is None

def test_non_push_markets_unchanged_by_commit_4():
    for p,o,opp in [(.62,-150,130),(.55,120,-140),(.58,105,-125)]:
        a=score_mlb_edge(model_p=p,american_odds=o,opposite_odds=opp)
        b=score_mlb_edge(model_p=p,american_odds=o,opposite_odds=opp,push_probability=0.0)
        profit=100/(-o) if o<0 else o/100
        assert abs(a.ev_per_dollar-(p*profit-(1-p)))<1e-12
        assert abs(a.edge-(p-a.market_p))<1e-12
        assert a.fair_odds==fair_american_odds(p)
        assert "PUSH_AWARE_SETTLEMENT" not in a.reason_codes
        assert (a.status,a.confidence_score,a.edge,a.ev_per_dollar)==(b.status,b.confidence_score,b.edge,b.ev_per_dollar)

def test_invalid_push_mass_raises():
    import pytest
    from sportsedge.mlb_edge_score import MLBEdgeScoreError
    with pytest.raises(MLBEdgeScoreError,match="MODEL_PUSH_MASS_INVALID"):
        score_mlb_edge(model_p=.60,american_odds=-110,opposite_odds=-110,push_probability=.40,push_possible=True)
    with pytest.raises(MLBEdgeScoreError,match="MODEL_PUSH_MASS_INVALID"):
        score_mlb_edge(model_p=.50,american_odds=-110,opposite_odds=-110,push_probability=-.01,push_possible=True)
