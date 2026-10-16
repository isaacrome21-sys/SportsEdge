"""NFL no-factors card suppression, including the Bills/Rams 54.5 incident.

These fixtures use public-source-shaped offline responses; no market price can
be used to confer data verification or to fill an unknown score projection.
"""
from datetime import datetime, timezone

from artifacts import free_models
from artifacts.run_it_full import run_full
from sportsedge.prepricing import factor_ingestion as fi
from tests.test_prepricing_ingestion import (
    FakeGetter, nfl_mapping, nfl_row, NOW, ESPN, KICKOFF_NFL,
)


def _nfl_lines():
    return [
        nfl_row(market="TOTAL", side="UNDER", line=54.5, odds=-102,
                quote_captured_at=NOW.isoformat()),
        nfl_row(market="TOTAL", side="OVER", line=54.5, odds=-118,
                quote_captured_at=NOW.isoformat()),
    ]


def test_nfl_direct_context_missing_both_histories_blocks_before_ev():
    mapping = nfl_mapping()
    for team_id in ("1", "33"):
        mapping[f"{ESPN}/football/nfl/teams/{team_id}/schedule?season=2026"] = {"events": []}
    card = free_models.run({"lines": _nfl_lines()}, now=NOW, getter=FakeGetter(mapping))
    assert not card["edges"]
    assert not card["independent_candidates"]
    assert not card["lane_b_edges"]
    for row in card["evaluated_rows"]:
        assert row["status"] == "BLOCKED_NFL_CRITICAL_CONTEXT_UNVERIFIED"
        assert "HOME_HISTORY_COUNT" in row["reason"]
        assert "AWAY_HISTORY_COUNT" in row["reason"]
        assert row.get("estimate_p") is None
        assert row.get("ev_per_dollar") is None


def test_nfl_direct_context_missing_one_team_blocks():
    mapping = nfl_mapping()
    mapping[f"{ESPN}/football/nfl/teams/1/schedule?season=2026"] = {"events": []}
    card = free_models.run({"lines": [nfl_row(market="TOTAL", side="UNDER",
                              line=54.5, odds=-102)]}, now=NOW,
                           getter=FakeGetter(mapping))
    row = card["evaluated_rows"][0]
    assert row["status"] == "BLOCKED_NFL_CRITICAL_CONTEXT_UNVERIFIED"
    assert "HOME_HISTORY_COUNT" in row["reason"]
    assert "AWAY_HISTORY_COUNT" not in row["reason"]


def test_nfl_direct_context_missing_injury_receipts_blocks():
    mapping = nfl_mapping()
    mapping[f"{ESPN}/football/nfl/teams/1/injuries"] = {"unexpected": "schema"}
    mapping[f"{ESPN}/football/nfl/injuries"] = {"unexpected": "schema"}
    card = free_models.run({"lines": [nfl_row(market="TOTAL", side="UNDER",
                              line=54.5, odds=-102)]}, now=NOW,
                           getter=FakeGetter(mapping))
    row = card["evaluated_rows"][0]
    assert row["status"] == "BLOCKED_NFL_CRITICAL_CONTEXT_UNVERIFIED"
    assert "HOME_INJURIES" in row["reason"]


def test_nfl_prepricing_missing_one_team_prior_history_blocks():
    mapping = nfl_mapping()
    mapping[f"{ESPN}/football/nfl/teams/1/schedule?season=2026"] = {"events": []}
    (stage,) = fi.stage_games([nfl_row()], now=NOW, getter=FakeGetter(mapping))
    assert stage["blocked"] is True
    assert stage["block_reason"] == fi.BLOCK_NFL_TEAM_HISTORY
    assert "HOME" in stage["block_detail"]
    assert stage["adjustments"] == {}
    teams = [factor for factor in stage["factors"]
             if factor["factor"] == "team_strength_ratings"]
    assert teams and teams[0]["status"] == "MISSING"


def test_nfl_phone_runner_missing_team_history_has_no_probability():
    mapping = nfl_mapping()
    mapping[f"{ESPN}/football/nfl/teams/1/schedule?season=2026"] = {"events": []}
    result = run_full({"lines": _nfl_lines()}, now=NOW, getter=FakeGetter(mapping))
    assert len(result["evaluated_rows"]) == 2
    assert not result.get("edges")
    for row in result["evaluated_rows"]:
        assert row["status"] == fi.BLOCK_NFL_TEAM_HISTORY
        assert row.get("estimate_p") is None
        assert row.get("ev_per_dollar") is None


def test_nfl_no_fetch_can_show_diagnostic_but_never_rank():
    card = free_models.run({"lines": _nfl_lines()}, now=NOW,
                           auto_context=False)
    assert len(card["evaluated_rows"]) == 2
    assert not card["edges"]
    assert not card["independent_candidates"]
    assert not card["lane_b_edges"]
    assert len(card["lane_a_research_diagnostics"]) == 2
    for row in card["evaluated_rows"]:
        assert row["status"] == "WATCH_NFL_NO_VERIFIED_CONTEXT"
        assert row["research_only"] is True
        assert row["model_validation"] == "NOT_PROVEN_VS_CLOSE"


def test_nfl_verified_two_team_inputs_still_run_unvalidated_research():
    card = free_models.run({"lines": _nfl_lines()}, now=NOW,
                           getter=FakeGetter(nfl_mapping()))
    assert len(card["evaluated_rows"]) == 2
    for row in card["evaluated_rows"]:
        assert row["status"] not in {
            "BLOCKED_NFL_CRITICAL_CONTEXT_UNVERIFIED",
            "WATCH_NFL_NO_VERIFIED_CONTEXT",
        }
        assert row["research_only"] is True
        assert row["validated_profitability"] is False
