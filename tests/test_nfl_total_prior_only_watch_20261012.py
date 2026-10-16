"""NFL true-total eligibility: having team histories is not a scoring model.

Free NFL runner uses league 22 pts/team + bounded margin/form adjustments.
The same inputs can price spreads, but total EV cannot be promoted by that
margin-only mechanism, even with both history/injury receipts present.
"""
from datetime import timedelta

from artifacts.free_models import run
from artifacts.run_it_full import run_full
from tests.test_prepricing_ingestion import FakeGetter, nfl_mapping, nfl_row, NOW


def paired_totals():
    return [
        nfl_row(market="TOTAL", side="UNDER", line=54.5,
                odds=-102, quote_captured_at=NOW.isoformat()),
        nfl_row(market="TOTAL", side="OVER", line=54.5,
                odds=-118, quote_captured_at=NOW.isoformat()),
    ]


def test_verified_histories_do_not_promote_44_pt_league_prior_total():
    card = run({"lines": paired_totals()}, now=NOW,
               getter=FakeGetter(nfl_mapping()))
    assert len(card["evaluated_rows"]) == 2
    assert card["edges"] == []
    assert card["independent_candidates"] == []
    assert card["lane_b_edges"] == []
    assert len(card["lane_a_research_diagnostics"]) == 2
    for item in card["evaluated_rows"]:
        assert item["status"] == "WATCH_NFL_TOTAL_PRIOR_ONLY"
        assert "NFL_ABSOLUTE_SCORING_RATE_MODEL_MISSING" in item["reason"]
        assert any(n.startswith("HOME_HISTORY_COUNT:") for n in item["context_notes"])
        assert any(n.startswith("AWAY_HISTORY_COUNT:") for n in item["context_notes"])
        assert item["research_only"] is True
        assert item["validated_profitability"] is False
        assert "independent_projection" in item


def test_phone_run_it_does_not_rank_verified_but_uncalibrated_nfl_totals():
    card = run_full({"lines": paired_totals()}, now=NOW,
                    getter=FakeGetter(nfl_mapping()))
    assert len(card["evaluated_rows"]) == 2
    assert not card["edges"]
    assert not card["independent_candidates"]
    assert not card["lane_b_edges"]
    for item in card["evaluated_rows"]:
        assert item["status"] == "WATCH_NFL_TOTAL_PRIOR_ONLY"
        assert "22_PTS_PER_TEAM_PLUS_MARGIN_FORM_ONLY" in item["reason"]
    assert card["summary"]["status_counts"]["WATCH_NFL_TOTAL_PRIOR_ONLY"] == 2


def test_stale_quote_remains_explicit_first_blocker():
    stale = (NOW - timedelta(seconds=600)).isoformat()
    tickets = paired_totals()
    for ticket in tickets:
        ticket["quote_captured_at"] = stale
    card = run({"lines": tickets}, now=NOW,
               getter=FakeGetter(nfl_mapping()))
    assert card["edges"] == []
    assert card["lane_b_edges"] == []
    assert card["independent_candidates"] == []
    assert {r["status"] for r in card["evaluated_rows"]} == {"WATCH_QUOTE_NOT_CURRENT"}


def test_nfl_spread_not_misclassified_as_total():
    tickets = [nfl_row(market="SPREAD", side="AWAY", line=3.5,
                       odds=-118, quote_captured_at=NOW.isoformat())]
    card = run({"lines": tickets}, now=NOW,
               getter=FakeGetter(nfl_mapping()))
    assert len(card["evaluated_rows"]) == 1
    row = card["evaluated_rows"][0]
    assert row["status"] != "WATCH_NFL_TOTAL_PRIOR_ONLY"
    assert row["research_only"] is True
    assert row["validated_profitability"] is False


def test_book_anchored_lane_also_cannot_turn_prior_total_into_edge():
    card = run({"lines": paired_totals()}, now=NOW, lane="B",
               getter=FakeGetter(nfl_mapping()))
    assert card["edges"] == []
    assert card["lane_b_edges"] == []
    for r in card["evaluated_rows"]:
        assert r["status"] == "WATCH_NFL_TOTAL_PRIOR_ONLY"
        assert r["pricing_lane"] == "LANE_B_ANCHORED"
