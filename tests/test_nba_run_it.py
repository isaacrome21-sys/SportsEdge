from datetime import datetime, timezone
from sportsedge.sports.nba.binding import NBAQuote, bind_quote
from sportsedge.sports.nba.pricing import NBAFairPrice
from sportsedge.sports.nba.run_it import build_run_it_card


NOW=datetime(2026,9,22,20,0,tzinfo=timezone.utc)


def edge(market="TOTAL", selection="OVER", score_quality=1.0):
    q=NBAQuote("g1",market,selection,225.5,2.0,"BOOK",NOW)
    fair=NBAFairPrice(.56,0,.44,1/.56)
    return bind_quote(q,fair,as_of=NOW,model_quality=score_quality,context_quality=1.0)


def test_card_exposes_probability_ev_and_score_without_recomputing_them():
    e=edge()
    c=build_run_it_card([e],generated_at=NOW)
    r=c.rows[0]
    assert r.model_probability == e.fair.win_probability
    assert r.ev == e.ev and r.score == e.score
    assert r.score_version == "NBA_RUN_IT_SCORE_V1"


def test_card_marks_unsupported_and_does_not_emit_it():
    supported=edge()
    unsupported=edge("FIRST_BASKET","PLAYER X")
    c=build_run_it_card([supported,unsupported],generated_at=NOW,requested_markets=["TOTAL","FIRST_BASKET","TRIPLE_DOUBLE"])
    assert tuple(r.market for r in c.rows) == ("TOTAL",)
    assert c.unsupported_markets == ("FIRST_BASKET","TRIPLE_DOUBLE")


def test_score_filter_and_future_time_fail_closed():
    import pytest
    e=edge()
    assert not build_run_it_card([e],generated_at=NOW,minimum_score=100).rows
    future=e.__class__(e.quote.__class__(e.quote.game_id,e.quote.market,e.quote.selection,e.quote.line,e.quote.decimal_odds,e.quote.book,datetime(2026,9,22,20,1,tzinfo=timezone.utc)),e.fair,e.ev,e.score,e.score_version)
    with pytest.raises(ValueError):
        build_run_it_card([future],generated_at=NOW)
