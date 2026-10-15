"""MLB Total Hits wiring tests. Offline fixtures only.

Proves the Total Hits families land as first-class intake with
truthful NO_ENGINE terminal states (sportsedge.mlb_total_hits):

* GAME_TOTAL_HITS terminates at TOTAL_HITS_DISTRIBUTION_UNCONSTRUCTED
  (no joint distribution exists and an independence convolution of
  per-batter marginals would fabricate one);
* TEAM_TOTAL_HITS terminates at TEAM_TOTAL_HITS_MODEL_HARNESS_FAIL --
  the one constructed candidate (team-rate Poisson) carries a
  recorded out-of-sample harness FAIL and must not price;
* malformed rows refuse by name (P0-style identity discipline);
* no row, well-formed or malformed, can carry a price, probability
  or EV, through the stage or through run_full.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sportsedge.mlb_total_hits import (
    GAME_TOTAL_HITS_TEAM_IDENTITY_UNEXPECTED,
    TEAM_TOTAL_HITS_MODEL_HARNESS_FAIL,
    TEAM_TOTAL_HITS_TEAM_REQUIRED,
    TEAM_TOTAL_HITS_TEAM_SIDE_CONFLICT,
    TEAM_TOTAL_HITS_TEAM_SIDE_INVALID,
    TOTAL_HITS_DISTRIBUTION_UNCONSTRUCTED,
    TOTAL_HITS_LINE_INVALID,
    TOTAL_HITS_SIDE_INVALID,
    canonical_total_hits_market,
    phone_total_hits_rows,
)

NOW = datetime(2026, 9, 14, 23, 0, tzinfo=timezone.utc)
KICKOFF = "2026-09-14T23:10:00Z"

PRICE_KEYS = ("model_p", "model_probability", "probability", "ev",
              "estimated_ev", "odds", "american_odds", "price")


def _game_row(**over):
    base = {"sport": "MLB", "market": "GAME_TOTAL_HITS",
            "book": "draftkings", "away": "Away Club", "home": "Home Club",
            "kickoff": KICKOFF, "side": "OVER", "line": 14.5, "odds": -110,
            "quote_captured_at": "2026-09-14T22:59:00Z"}
    base.update(over)
    return base


def _team_row(**over):
    base = {"sport": "MLB", "market": "TEAM_TOTAL_HITS",
            "book": "draftkings", "away": "Away Club", "home": "Home Club",
            "kickoff": KICKOFF, "side": "OVER", "line": 7.5, "odds": -115,
            "team_side": "HOME", "quote_captured_at": "2026-09-14T22:59:00Z"}
    base.update(over)
    return base


def _assert_refusal(result, code):
    assert result["status"] == "NO_MODEL_OR_MARKET"
    assert result["total_hits_reason"] == code
    assert result["research_only"] is True
    for key in PRICE_KEYS:
        assert key not in result, key


# ---------------------------------------------------------- family gates

def test_game_total_hits_terminates_unconstructed():
    results, receipts = phone_total_hits_rows([_game_row()], now=NOW)
    _assert_refusal(results[0], TOTAL_HITS_DISTRIBUTION_UNCONSTRUCTED)
    assert results[0]["blocker"] == "NO_ENGINE"
    assert "dependence" in results[0]["blocker_detail"]
    assert receipts[0]["outcome_counts"] == {
        TOTAL_HITS_DISTRIBUTION_UNCONSTRUCTED: 1}


def test_game_total_hits_at_catalog_line_14_5():
    # The Oct 13 catalog's game Total Hits line.
    results, _ = phone_total_hits_rows([_game_row(line=14.5)], now=NOW)
    _assert_refusal(results[0], TOTAL_HITS_DISTRIBUTION_UNCONSTRUCTED)


def test_team_total_hits_terminates_harness_fail():
    results, receipts = phone_total_hits_rows([_team_row()], now=NOW)
    _assert_refusal(results[0], TEAM_TOTAL_HITS_MODEL_HARNESS_FAIL)
    assert results[0]["blocker"] == "NO_ENGINE"
    assert "naive" in results[0]["blocker_detail"]
    assert receipts[0]["status"] == "TOTAL_HITS_REFUSAL_ACTIVE_NO_ENGINE"


def test_team_total_hits_at_catalog_line_7_5_both_teams():
    rows = [_team_row(team_side="AWAY"), _team_row(team_side="HOME")]
    results, _ = phone_total_hits_rows(rows, now=NOW)
    for result in results:
        _assert_refusal(result, TEAM_TOTAL_HITS_MODEL_HARNESS_FAIL)


def test_stage_has_no_pricing_surface():
    import sportsedge.mlb_total_hits as module
    public = [name for name in dir(module) if not name.startswith("_")]
    assert not any(name.startswith("price") for name in public)
    assert not hasattr(module, "price_total_hits")
    assert not hasattr(module, "price_game_total_hits")


# ------------------------------------------------------ intake resolution

def test_bare_total_hits_is_game_market_without_team_identity():
    assert canonical_total_hits_market({"market": "TOTAL_HITS"}) == "GAME_TOTAL_HITS"


def test_bare_total_hits_with_team_identity_is_team_market():
    row = {"market": "TOTAL_HITS", "team_side": "AWAY"}
    assert canonical_total_hits_market(row) == "TEAM_TOTAL_HITS"
    row = {"market": "TOTAL_HITS", "team": "Home Club"}
    assert canonical_total_hits_market(row) == "TEAM_TOTAL_HITS"


def test_explicit_names_decide_by_name():
    assert canonical_total_hits_market(
        {"market": "TEAM_TOTAL_HITS"}) == "TEAM_TOTAL_HITS"
    assert canonical_total_hits_market(
        {"market": "GAME_HITS"}) == "GAME_TOTAL_HITS"
    assert canonical_total_hits_market({"market": "TOTALS"}) is None
    assert canonical_total_hits_market({"market": "TEAM_HITS"}) is None


def test_bare_total_hits_row_routes_by_identity_through_stage():
    game = _game_row(market="TOTAL_HITS")
    team = _team_row(market="TOTAL_HITS")
    results, _ = phone_total_hits_rows([game, team], now=NOW)
    _assert_refusal(results[0], TOTAL_HITS_DISTRIBUTION_UNCONSTRUCTED)
    _assert_refusal(results[1], TEAM_TOTAL_HITS_MODEL_HARNESS_FAIL)


# ------------------------------------------------------------ malformed

def test_side_invalid_refused():
    results, _ = phone_total_hits_rows([_game_row(side="YES")], now=NOW)
    _assert_refusal(results[0], TOTAL_HITS_SIDE_INVALID)
    assert results[0]["blocker"] == "NO_QUOTE"


def test_missing_side_refused():
    row = _team_row()
    row.pop("side")
    results, _ = phone_total_hits_rows([row], now=NOW)
    _assert_refusal(results[0], TOTAL_HITS_SIDE_INVALID)


def test_line_invalid_refused():
    for bad in (None, "abc", -1, float("nan")):
        results, _ = phone_total_hits_rows([_game_row(line=bad)], now=NOW)
        _assert_refusal(results[0], TOTAL_HITS_LINE_INVALID)


def test_game_row_with_team_identity_refused():
    results, _ = phone_total_hits_rows(
        [_game_row(team_side="HOME")], now=NOW)
    _assert_refusal(results[0], GAME_TOTAL_HITS_TEAM_IDENTITY_UNEXPECTED)


def test_team_row_without_team_refused():
    row = _team_row()
    row.pop("team_side")
    results, _ = phone_total_hits_rows([row], now=NOW)
    _assert_refusal(results[0], TEAM_TOTAL_HITS_TEAM_REQUIRED)


def test_team_side_garbage_refused():
    results, _ = phone_total_hits_rows(
        [_team_row(team_side="MIDDLE")], now=NOW)
    _assert_refusal(results[0], TEAM_TOTAL_HITS_TEAM_SIDE_INVALID)


def test_team_side_named_team_resolves():
    # A team name in team_side is resolvable (mirrors the P0 contract).
    results, _ = phone_total_hits_rows(
        [_team_row(team_side="Home Club")], now=NOW)
    _assert_refusal(results[0], TEAM_TOTAL_HITS_MODEL_HARNESS_FAIL)


def test_team_side_conflict_refused():
    results, _ = phone_total_hits_rows(
        [_team_row(team_side="HOME", team="Away Club")], now=NOW)
    _assert_refusal(results[0], TEAM_TOTAL_HITS_TEAM_SIDE_CONFLICT)


def test_team_side_agreement_passes_shape():
    results, _ = phone_total_hits_rows(
        [_team_row(team_side="HOME", team="Home Club")], now=NOW)
    _assert_refusal(results[0], TEAM_TOTAL_HITS_MODEL_HARNESS_FAIL)


# ------------------------------------------------------------- run_full

@pytest.mark.registry_lane_internals
def test_total_hits_rows_through_run_full():
    from artifacts.run_it_full import run_full
    rows = [_game_row(), _team_row(), _game_row(market="TOTAL_HITS")]
    card = run_full({"lines": rows, "sport": "MLB"}, now=NOW,
                    auto_context=False)
    evaluated = card["evaluated_rows"]
    assert len(evaluated) == 3
    codes = [r["total_hits_reason"] for r in evaluated]
    assert codes == [TOTAL_HITS_DISTRIBUTION_UNCONSTRUCTED,
                     TEAM_TOTAL_HITS_MODEL_HARNESS_FAIL,
                     TOTAL_HITS_DISTRIBUTION_UNCONSTRUCTED]
    for result in evaluated:
        assert result["status"] == "NO_MODEL_OR_MARKET"
        assert result["blocker"] == "NO_ENGINE"
        assert "NO_VERIFIED_MODEL_FOR_THIS_MARKET" not in result["reason"]
    assert card["prop_model_status"]["mlb_total_hits"].startswith("NO_ENGINE")
