from datetime import datetime, timezone
import pytest
from sportsedge.sports.nba.binding import NBAQuote, bind_quote
from sportsedge.sports.nba.calibrated_binding import NBAProbabilityProvenance
from sportsedge.sports.nba.pricing import NBAFairPrice
from sportsedge.sports.nba.run_it import build_run_it_card


NOW=datetime(2026,9,22,20,0,tzinfo=timezone.utc)


def edge(market="TOTAL", selection="OVER", score_quality=1.0, odds=2.0):
    q=NBAQuote("g1",market,selection,225.5,odds,"BOOK",NOW)
    fair=NBAFairPrice(.56,0,.44,1/.56)
    return bind_quote(q,fair,as_of=NOW,model_quality=score_quality,context_quality=1.0)


def identity(e):
    q=e.quote
    return q.game_id,q.market,q.selection,q.line,q.book


def provenance(e, sim="sim"):
    p=e.fair.win_probability
    return NBAProbabilityProvenance(p,p,"m1",sim,None,None)


def test_card_exposes_probability_ev_and_score_without_recomputing_them():
    e=edge()
    c=build_run_it_card([e],generated_at=NOW)
    r=c.rows[0]
    assert r.model_probability == e.fair.win_probability
    assert r.ev == e.ev and r.score == e.score
    assert r.score_version == "NBA_RUN_IT_SCORE_RULE_B_V2"


def test_card_marks_unsupported_and_does_not_emit_it():
    supported=edge()
    unsupported=edge("FIRST_BASKET","PLAYER X")
    c=build_run_it_card([supported,unsupported],generated_at=NOW,requested_markets=["TOTAL","FIRST_BASKET","TRIPLE_DOUBLE"])
    assert tuple(r.market for r in c.rows) == ("TOTAL",)
    assert c.unsupported_markets == ("FIRST_BASKET","TRIPLE_DOUBLE")


def test_score_filter_and_future_time_fail_closed():
    e=edge()
    assert build_run_it_card([e],generated_at=NOW,minimum_score=100).rows
    with pytest.raises(ValueError):
        build_run_it_card([e],generated_at=NOW,minimum_score=101)
    future=e.__class__(e.quote.__class__(e.quote.game_id,e.quote.market,e.quote.selection,e.quote.line,e.quote.decimal_odds,e.quote.book,datetime(2026,9,22,20,1,tzinfo=timezone.utc)),e.fair,e.ev,e.score,e.score_version)
    with pytest.raises(ValueError):
        build_run_it_card([future],generated_at=NOW)


def test_card_can_require_and_expose_probability_provenance():
    e=edge()
    prov=provenance(e)
    c=build_run_it_card([e],generated_at=NOW,provenance_by_identity={identity(e):prov},require_provenance=True)
    assert c.rows[0].provenance == prov
    with pytest.raises(ValueError,match="missing probability provenance"):
        build_run_it_card([e],generated_at=NOW,require_provenance=True)
    bad=NBAProbabilityProvenance(.55,.55,"m1","sim",None,None)
    with pytest.raises(ValueError,match="does not match"):
        build_run_it_card([e],generated_at=NOW,provenance_by_identity={identity(e):bad},require_provenance=True)


def test_bettor_board_ranks_ev_before_score():
    high_score=edge(score_quality=1.0,odds=1.90)
    high_ev=edge(selection="UNDER",score_quality=.64,odds=2.20)
    c=build_run_it_card([high_score,high_ev],generated_at=NOW)
    assert c.rows[0].selection == "UNDER"
    assert c.rows[0].ev > c.rows[1].ev
    assert c.rows[0].score < c.rows[1].score
