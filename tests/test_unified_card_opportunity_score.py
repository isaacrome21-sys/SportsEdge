from types import SimpleNamespace
from sportsedge.unified_card import _convert, unified_result_to_dict

def _result(model_p=.69, odds=-185):
    return SimpleNamespace(game_id="g1", market="PASS_TDS", entity_id="qb1", line=1.5,
        side="OVER", american_odds=odds, model_p=model_p, bet_status="BET",
        reason="priced")

def test_unified_card_exposes_native_fair_price_score_and_stars():
    r=_convert(_result())
    assert r.fair_american_odds == -223
    assert r.sportsedge_score is not None
    assert r.stars is not None
    assert r.opportunity_edge_probability_points > 0

def test_serialized_card_keeps_probability_separate_from_score():
    row=unified_result_to_dict(_convert(_result(.475,150)))
    assert row["model_p"] == .475
    assert row["fair_american_odds"] == 111
    assert row["sportsedge_score"] != 48

def test_unmodeled_card_does_not_invent_score():
    r=_convert(_result(None,-110))
    assert r.fair_american_odds is None
    assert r.sportsedge_score is None
    assert r.stars is None
