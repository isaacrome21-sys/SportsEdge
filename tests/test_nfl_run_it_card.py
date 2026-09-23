import pytest

from sportsedge.nfl_run_it import AUTHORITY_FOOTER, NflRunItError, run_it
from sportsedge.nfl_run_it_scoring import SCORE_LABEL

NOW = "2026-09-21T10:45:00Z"

def _q(**kwargs):
    base = {"game_id":"2026-W3-KC-NYJ","home":"KC","away":"NYJ","book":"dk","retrieved_at":NOW}
    base.update(kwargs)
    return base

def test_empty_slate_is_valid_and_non_certifying():
    card=run_it([],[],as_of=NOW)
    assert card.picks == ()
    assert card.empty_reason == "Nothing looks strong enough."
    assert card.render().endswith(AUTHORITY_FOOTER)

def test_one_sided_quote_is_refused():
    with pytest.raises(NflRunItError, match="PAIRED_PRICE_REQUIRED"):
        run_it([_q(market="moneyline",selection="KC",price_american=-150)],[],as_of=NOW)

def test_retrieved_at_is_required_and_stale_quotes_fail_closed():
    missing=[_q(market="moneyline",selection="KC",price_american=-150,retrieved_at=None),_q(market="moneyline",selection="NYJ",price_american=130)]
    with pytest.raises(NflRunItError, match="QUOTE_RETRIEVED_AT_REQUIRED"): run_it(missing,[],as_of=NOW)
    stale=[_q(market="moneyline",selection="KC",price_american=-150,retrieved_at="2026-09-21T10:41:59Z"),_q(market="moneyline",selection="NYJ",price_american=130,retrieved_at="2026-09-21T10:41:59Z")]
    with pytest.raises(NflRunItError, match="QUOTE_STALE"): run_it(stale,[],as_of=NOW)

def test_model_p_field_is_forbidden_on_non_certifying_card():
    quotes=[_q(market="moneyline",selection="KC",price_american=-150),_q(market="moneyline",selection="NYJ",price_american=130)]
    with pytest.raises(NflRunItError, match="MODEL_P_FIELD_FORBIDDEN_USE_ESTIMATE_P"):
        run_it(quotes,[_q(market="moneyline",selection="KC",line=None,model_p=.70)],as_of=NOW)

def test_integer_spread_scalar_estimate_requires_joint_simulations():
    quotes=[_q(market="spread",selection="KC",line=-3.,price_american=-110),_q(market="spread",selection="NYJ",line=3.,price_american=-110)]
    with pytest.raises(NflRunItError, match="SIMULATIONS_REQUIRED_FOR_INTEGER_LINE"):
        run_it(quotes,[_q(market="spread",selection="KC",line=-3.,estimate_p=.57)],as_of=NOW)

def test_integer_spread_simulation_preserves_push_and_score_b_is_not_ev():
    quotes=[_q(market="spread",selection="KC",line=-3.,price_american=-110),_q(market="spread",selection="NYJ",line=3.,price_american=-110)]
    rows=([{"home_score":27,"away_score":17} for _ in range(60)]+[{"home_score":27,"away_score":24} for _ in range(20)]+[{"home_score":20,"away_score":24} for _ in range(20)])
    card=run_it(quotes,[],simulations={"2026-W3-KC-NYJ":rows},edge_floor=.02,as_of=NOW)
    assert len(card.picks)==1
    p=card.picks[0]
    assert p.selection=="KC" and p.push_p==pytest.approx(.20)
    assert p.ev_per_dollar==pytest.approx(.60*(100/110)-.20)
    assert p.fair_american==-300
    assert p.score_0_100==0  # flags not wired yet: fail closed, never EV-derived
    assert p.score_label==SCORE_LABEL

def test_noninteger_markets_rank_by_ev_then_edge_not_score():
    quotes=[_q(market="spread",selection="KC",line=-2.5,price_american=-105),_q(market="spread",selection="NYJ",line=2.5,price_american=-115),_q(market="total",selection="OVER",line=47.5,price_american=-108),_q(market="total",selection="UNDER",line=47.5,price_american=-112)]
    estimates=[_q(market="spread",selection="KC",line=-2.5,estimate_p=.57),_q(market="total",selection="OVER",line=47.5,estimate_p=.56)]
    card=run_it(quotes,estimates,edge_floor=.015,as_of=NOW)
    evs=[p.ev_per_dollar for p in card.picks]
    assert evs==sorted(evs,reverse=True)
    assert all(p.score_0_100==0 for p in card.picks)

def test_longshot_over_plus_400_uses_sensitivity_gate():
    quotes=[_q(market="moneyline",selection="NYJ",price_american=500),_q(market="moneyline",selection="KC",price_american=-800)]
    with pytest.raises(NflRunItError, match="DEVIG_METHOD_SENSITIVITY"):
        run_it(quotes,[_q(market="moneyline",selection="NYJ",line=None,estimate_p=.20)],as_of=NOW)
