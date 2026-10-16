"""Projection-first, exact two-sided no-vig research comparison tests.

The independent projection is a MARKET-BLIND unvalidated team-score heuristic.
These tests do not claim the model beats live betting odds or validates props.
"""
from datetime import datetime, timezone
from pathlib import Path
import importlib.util
import math

ROOT=Path(__file__).resolve().parents[1]
engine_spec=importlib.util.spec_from_file_location("free_projection_card",ROOT/"artifacts"/"free_models.py")
engine=importlib.util.module_from_spec(engine_spec)
engine_spec.loader.exec_module(engine)
phone_spec=importlib.util.spec_from_file_location("free_projection_phone",ROOT/"scripts"/"free_models_phone_issue.py")
phone=importlib.util.module_from_spec(phone_spec)
phone_spec.loader.exec_module(phone)
NOW=datetime(2026,10,11,13,0,tzinfo=timezone.utc)
KICKOFF="2026-10-12T01:15:00Z"


def row(market="TOTAL",side="UNDER",line=54.5,odds=-105,**extra):
    base={"away":"Buffalo Bills","home":"Los Angeles Rams",
          "market":market,"side":side,"odds":odds,"kickoff":KICKOFF,
          # Fresh capture so the centralized 180s freshness gate does not mask
          # candidate assertions; override per-test where staleness is the point.
          "quote_captured_at":"2026-10-11T12:59:00Z"}
    if line is not None:
        base["line"]=line
    base.update(extra)
    return base


def card(rows):
    return engine.run({"sport":"NFL","lines":rows},now=NOW,auto_context=False)


def test_total_two_side_no_vig_and_market_blind_projection():
    c=card([row(),row(side="OVER",odds=-115)])
    assert len(c["evaluated_rows"])==2
    under,over=c["evaluated_rows"]
    u=under["independent_projection"]
    o=over["independent_projection"]
    assert u["family"]=="FREE_TEAM_SCORE_HEURISTIC_UNVALIDATED"
    assert u["uses_sportsbook_price_in_projection"] is False
    assert u["validated_vs_close"] is False
    assert u["paired_market_status"]=="EXACT_DK_TWO_SIDED_NO_VIG_RESEARCH"
    assert abs(u["market_no_vig_p"]+o["market_no_vig_p"]-1)<1e-5
    assert abs(u["estimate_p"]+o["estimate_p"]-1)<1e-5
    assert u["projected_total"]==o["projected_total"]
    assert u["projected_total"]!=under["market_anchor"]["fair_total"]
    assert u["fair_american"] is not None
    # No-fetch prices remain available to audit projection arithmetic, never
    # ranked as game-specific betting opportunities.
    assert c["independent_candidates"] == []
    assert any(r["selection"]=="UNDER 54.5" for r in c["lane_a_research_diagnostics"])
    assert all(r["status"] == "WATCH_NFL_NO_VERIFIED_CONTEXT"
               for r in c["evaluated_rows"])
    assert c["authority"]["official"] is False


def test_independent_probabilities_do_not_change_with_price():
    first=card([row(odds=-105),row(side="OVER",odds=-115)])
    second=card([row(odds=-110),row(side="OVER",odds=-110)])
    a,b=first["evaluated_rows"][0],second["evaluated_rows"][0]
    assert a["independent_projection"]["estimate_p"]==b["independent_projection"]["estimate_p"]
    assert a["independent_projection"]["projected_total"]==b["independent_projection"]["projected_total"]
    assert a["independent_projection"]["market_no_vig_p"]!=b["independent_projection"]["market_no_vig_p"]
    assert a["independent_projection"]["ev_per_dollar"]!=b["independent_projection"]["ev_per_dollar"]


def test_moneyline_no_vig_from_exact_opposite_and_model_stays_market_blind():
    c=card([row(market="ML",side="AWAY",line=None,odds=145,opposite_odds=-175),
            row(market="ML",side="HOME",line=None,odds=-175,opposite_odds=145)])
    away,home=c["evaluated_rows"]
    a,b=away["independent_projection"],home["independent_projection"]
    assert a["paired_market_status"]=="EXACT_DK_TWO_SIDED_NO_VIG_RESEARCH"
    assert abs(a["market_no_vig_p"]+b["market_no_vig_p"]-1)<1e-5
    assert all(r["odds_american"]>=-165 for r in c["independent_candidates"])
    assert any(r["odds_american"]==-175 for r in c["lane_a_research_diagnostics"])


def test_ml_conflicting_opposite_quoted_price_fails_closed():
    c=card([row(market="ML",side="AWAY",line=None,odds=145,opposite_odds=-175),
            row(market="ML",side="HOME",line=None,odds=-180,opposite_odds=145)])
    assert all(r["independent_projection"]["paired_market_status"] ==
               "OPPOSITE_ML_CONFLICT" for r in c["evaluated_rows"])
    assert c["independent_candidates"]==[]


def test_missing_and_wrong_threshold_or_opposite_never_infer_pair():
    single=card([row()])
    assert not single["independent_candidates"]
    assert single["evaluated_rows"][0]["independent_projection"]["paired_market_status"]=="MISSING_EXACT_OPPOSITE_DK_PRICE"
    bad=card([row(),row(side="OVER",line=55.5,odds=-115)])
    assert not bad["independent_candidates"]
    assert all("market_no_vig_p" not in r["independent_projection"] for r in bad["evaluated_rows"])
    spreads=card([row(market="SPREAD",side="AWAY",line=3.0,odds=100),
                  row(market="SPREAD",side="HOME",line=-3.5,odds=-120)])
    assert not spreads["independent_candidates"]
    assert all(r["independent_projection"]["paired_market_status"]==
               "MISSING_EXACT_OPPOSITE_DK_PRICE" for r in spreads["evaluated_rows"])


def test_contradictory_same_side_quotes_and_book_mixing_never_pass():
    c=card([row(),row(side="OVER",odds=-115),row(side="OVER",odds=-120)])
    assert c["evaluated_rows"][0]["independent_projection"]["paired_market_status"]=="MULTIPLE_CONTRADICTORY_PAIRS"
    c2=card([row(),row(side="OVER",odds=-115,book="pinnacle")])
    assert all(r["independent_projection"]["paired_market_status"]!="EXACT_DK_TWO_SIDED_NO_VIG_RESEARCH"
               for r in c2["evaluated_rows"])


def test_quoted_capture_times_must_not_be_proven_mismatched():
    c=card([row(quote_captured_at="2026-10-11T18:00:00Z"),
            row(side="OVER",odds=-115,quote_captured_at="2026-10-11T18:05:00Z")])
    assert all(r["independent_projection"]["paired_market_status"]==
               "MISMATCHED_QUOTE_TIMESTAMPS" for r in c["evaluated_rows"])
    assert c["independent_candidates"]==[]


def test_props_fail_closed_but_game_projection_research_card_still_works():
    c=card([row(),row(side="OVER",odds=-115),
            row(market="PASSING_YARDS",side="OVER",line=250.5,odds=-110)])
    assert c["summary"]["status_counts"]["BLOCKED_INVALID"]==1
    assert c["evaluated_rows"][2].get("independent_projection") is None
    md=phone.render_card(c)
    assert "**Projection-first research candidates" in md
    assert "DK no-vig p" in md
    assert "Raw EV" in md
    assert "Conservative book-anchored research" in md
    assert "UNVALIDATED" in md
    assert "**Factor verification" not in md


def test_no_verified_source_never_generates_independent_edges():
    no_game=engine.run({"lines":[dict(row(),sport="NFL")]},now=NOW,getter=lambda url:{})
    assert no_game["independent_candidates"]==[]
    assert no_game["evaluated_rows"][0]["status"]=="BLOCKED_CONTEXT_UNVERIFIED"
