"""NFL zero-context rejection against recorded ESPN fixtures.

This regression protects against publishing a 44-point default total as a
large theoretical +EV when neither team's recent game history was retrieved.
No live requests; odds never establish team strength or fixture identity.
"""
from artifacts import free_models
from artifacts.run_it_full import run_full
from sportsedge.prepricing import factor_ingestion as fi
from tests.test_prepricing_ingestion import (
    NOW, ESPN, FakeGetter, nfl_mapping, nfl_row,
)


def _missing_home_history():
    mapping = nfl_mapping()
    mapping[f"{ESPN}/football/nfl/teams/1/schedule?season=2026"] = {"events": []}
    return mapping


def test_nfl_prepricing_rejects_verified_fixture_without_team_history():
    (stage,) = fi.stage_games([nfl_row()], now=NOW,
                             getter=FakeGetter(_missing_home_history()))
    assert stage["blocked"] is True
    assert stage["block_reason"] == fi.BLOCK_NFL_TEAM_HISTORY_UNVERIFIED
    assert "HOME=0" in stage["block_detail"]
    assert stage["adjustments"] == {}
    assert any(f["factor"] == "team_strength_ratings" and f["status"] == "MISSING"
               for f in stage["factors"])


def test_nfl_phone_no_rank_when_one_team_history_missing():
    card = run_full({"lines": [
        nfl_row(market="TOTAL", side="UNDER", line=54.5, odds=-102),
        nfl_row(market="SPREAD", side="AWAY", line=3.5, odds=-118),
    ]}, now=NOW, getter=FakeGetter(_missing_home_history()))
    assert len(card["evaluated_rows"]) == 2
    assert all(r["status"] == fi.BLOCK_NFL_TEAM_HISTORY_UNVERIFIED
               for r in card["evaluated_rows"])
    assert all("estimate_p" not in r and "ev_per_dollar" not in r
               for r in card["evaluated_rows"])
    assert card["edges"] == []
    assert card["independent_candidates"] == []
    assert card["lane_b_edges"] == []


def test_standalone_engine_rejects_prior_only_nfl_with_live_context_mode():
    card = free_models.run({"lines": [
        nfl_row(market="TOTAL", side="UNDER", line=54.5, odds=-102),
    ]}, now=NOW, getter=FakeGetter(_missing_home_history()))
    assert card["evaluated_rows"][0]["status"] == "BLOCKED_NFL_TEAM_CONTEXT_UNVERIFIED"
    assert "HOME_VERIFIED_TEAM_HISTORY_LT_4" in card["evaluated_rows"][0]["reason"]
    assert card["edges"] == []
    assert card["independent_candidates"] == []
    assert card["lane_b_edges"] == []


def test_nfl_phone_blocks_explicit_no_fetch_despite_fresh_quote():
    card = run_full({"lines": [
        nfl_row(market="TOTAL", side="UNDER", line=54.5, odds=-102,
                quote_captured_at=NOW.isoformat()),
    ]}, now=NOW, auto_context=False)
    assert card["evaluated_rows"][0]["status"] == "BLOCKED_NFL_NO_VERIFIED_CONTEXT"
    assert not card["edges"] and not card["independent_candidates"]


def test_nfl_context_requires_both_independently_reported_injury_feeds():
    mapping = nfl_mapping()
    mapping[f"{ESPN}/football/nfl/teams/1/injuries"] = {"invalid": True}
    mapping[f"{ESPN}/football/nfl/injuries"] = {"invalid": True}
    card = free_models.run({"lines": [nfl_row()]}, now=NOW,
                           getter=FakeGetter(mapping))
    assert card["evaluated_rows"][0]["status"] == "BLOCKED_NFL_TEAM_CONTEXT_UNVERIFIED"
    assert "HOME_INJURY_SOURCE_UNVERIFIED" in card["evaluated_rows"][0]["reason"]
    assert card["edges"] == []


def test_nfl_good_fixture_and_four_game_histories_still_price_research():
    card = run_full({"lines": [nfl_row()]}, now=NOW,
                    getter=FakeGetter(nfl_mapping()))
    row = card["evaluated_rows"][0]
    assert row["status"] not in {
        fi.BLOCK_NFL_TEAM_HISTORY_UNVERIFIED,
        "BLOCKED_NFL_TEAM_CONTEXT_UNVERIFIED",
        "BLOCKED_NFL_NO_VERIFIED_CONTEXT",
    }
    assert "estimate_p" in row
    factors = card["prepricing_factor_audit"]["by_input_index"][0]["factors"]
    assert any(f["factor"] == "team_strength_ratings" and f["status"] == "USED"
               and "BOTH_TEAMS_VERIFIED_PRIOR_GAMES" in f["reason"]
               for f in factors)
    # Even complete source binding is not out-of-sample validation.
    assert row["validated_profitability"] is False
