"""Offline contract checks for the Oct 12 MLB research-market patch.

These tests never hit providers or assert a betting advantage. For market
mathematics they use deterministic fixed means and histories only.
"""
from datetime import datetime, timezone

import pytest

from artifacts import free_models
from artifacts.run_it_full import run_full
from sportsedge.mlb_batter_empirical import price_batter_market, BatterEmpiricalError
from sportsedge.mlb_phone_full_board import phone_market_board
from tests.test_prepricing_ingestion import FakeGetter, mlb_mapping, mlb_row
from sportsedge.prepricing import factor_ingestion as stage

NOW = datetime(2026, 10, 12, 19, 0, tzinfo=timezone.utc)
KICKOFF = "2026-10-12T21:00:00Z"


def _row(side="OVER", **changes):
    row = {
        "sport": "MLB", "away": "Los Angeles Dodgers",
        "home": "Milwaukee Brewers", "market": "TEAM_TOTALS",
        "side": side, "team": "Milwaukee Brewers",
        "line": 3.5, "odds": -110, "commence_time": KICKOFF,
        "quote_captured_at": "2026-10-12T18:59:00Z",
    }
    row.update(changes)
    return row


def test_team_totals_model_complements_at_half_line_and_pushes_at_integer():
    home, away = 3.35, 3.31
    for target in ("HOME", "AWAY"):
        p_over, push, = free_models.model_probability(
            "MLB", "TEAM_TOTALS", "OVER", 3.5, home, away, team_totals_team=target)
        p_under, push_u = free_models.model_probability(
            "MLB", "TEAM_TOTALS", "UNDER", 3.5, home, away, team_totals_team=target)
        assert push == push_u == 0
        assert p_over + p_under == pytest.approx(1, abs=1e-9)
        over, integer_push = free_models.model_probability(
            "MLB", "TEAM_TOTALS", "OVER", 3, home, away, team_totals_team=target)
        under, integer_push_u = free_models.model_probability(
            "MLB", "TEAM_TOTALS", "UNDER", 3, home, away, team_totals_team=target)
        assert 0 < integer_push == pytest.approx(integer_push_u)
        assert over + under + integer_push == pytest.approx(1, abs=1e-9)


def test_team_totals_requires_explicit_team_and_does_not_use_moneyline_anchor():
    provider = free_models.PublicContext(NOW, getter=lambda url: None)
    a = free_models.calculate(_row(), provider, NOW, auto_context=False)
    assert a["status"] in {"RESEARCH_POSITIVE_EV_UNVALIDATED", "BELOW_THRESHOLD", "PRICE_CAP"}
    assert a["market"] == "TEAM_TOTALS"
    assert a["team_totals_team"] == "HOME"
    assert a["selection"] == "Milwaukee Brewers OVER 3.5"
    assert a["pricing_lanes"]["lane_b_anchored"]["status"] == "LANE_B_UNAVAILABLE"
    assert a["pricing_lanes"]["lane_b_anchored"]["reason"] == "LANE_B_TEAM_TOTALS_UNVALIDATED"
    assert a["push_p"] == 0
    b = free_models.calculate(_row("Milwaukee Brewers Under", team=None),
                              provider, NOW, auto_context=False)
    assert b["team_totals_team"] == "HOME"
    assert b["selection"] == "Milwaukee Brewers UNDER 3.5"


def test_team_totals_wrong_team_or_unknown_side_fail_closed():
    provider = free_models.PublicContext(NOW, getter=lambda url: None)
    for bad in (
        _row(team=None), _row(team="New York Yankees"),
        _row(team="Los Angeles Dodgers", side="Milwaukee Brewers Over"),
        _row(side="YES"), _row(line=0),
    ):
        with pytest.raises(ValueError):
            free_models.calculate(bad, provider, NOW, auto_context=False)
    with pytest.raises(ValueError, match="UNSUPPORTED_MARKET_NO_PROP_MODEL"):
        free_models.calculate(_row(sport="NFL"), provider, NOW, auto_context=False)


def test_team_totals_phone_run_routes_and_preserves_both_sides_and_no_vig():
    pair = [_row("OVER"), _row("UNDER", odds=-115)]
    ticket = run_full({"lines": pair}, now=NOW, auto_context=False)
    results = ticket["evaluated_rows"]
    assert len(results) == 2
    assert all(row["market"] == "TEAM_TOTALS" for row in results)
    assert all(row["estimate_p"] is not None for row in results)
    assert all(row["pricing_lanes"]["lane_a_independent"]["family"] ==
               "FREE_TEAM_SCORE_HEURISTIC_UNVALIDATED" for row in results)
    assert all(row["independent_projection"]["paired_market_status"] ==
               "EXACT_DK_TWO_SIDED_NO_VIG_RESEARCH" for row in results)
    coverage = ticket["mlb_full_board"]["input_coverage"]
    assert "TEAM_TOTALS" in coverage["supplied_markets"]
    # t207u: these team-total rows are Lane A -> labeled diagnostics, not
    # priced research on the board.
    assert "TEAM_TOTALS" not in coverage["priced_research_markets"]
    assert coverage["lane_a_diagnostic_market_count"] >= 1


def test_missing_fixture_still_blocks_team_totals_before_pricing():
    ticket = run_full({"lines": [_row()]}, now=NOW, getter=lambda url: {})
    assert ticket["evaluated_rows"][0]["status"] == "BLOCKED_PREPRICING_FIXTURE_UNVERIFIED"
    assert "TEAM_TOTALS" in ticket["mlb_full_board"]["input_coverage"]["supplied_but_unpriced_markets"]


def test_batter_empirical_new_count_markets_are_research_only_and_strict():
    hist = [
        {"walks": i % 3, "strikeouts": (i + 1) % 3,
         "singles": i % 2, "doubles": i % 4,
         "hits_runs_rbis": i % 5}
        for i in range(20)
    ]
    for market in ("BATTER_BB", "BATTER_K", "BATTER_SINGLES",
                   "BATTER_DOUBLES", "HITS_RUNS_RBIS"):
        out = price_batter_market(
            market=market, side="OVER", line=0.5, pa_history=hist)
        assert 0 <= out["model_p"] <= 1
        assert out["push_p"] == 0
        assert out["engine"] == "mlb_batter_empirical_game_log_v1"
    with pytest.raises(BatterEmpiricalError, match="walks_INVALID"):
        price_batter_market(market="BATTER_BB", side="OVER", line=0.5,
                            pa_history=[{"strikeouts": 1} for _ in range(20)])


def test_new_batter_aliases_are_routed_not_marked_unrecognized():
    rows = [_row(market=market, team=None, side="OVER", line=0.5)
            for market in ("BATTER_BB", "BATTER_K", "SINGLES",
                           "DOUBLES", "HITS_RUNS_RBIS")]
    for row in rows:
        row["player_name"] = "Fictional Test Player"
    card = run_full({"lines": rows}, now=NOW, getter=lambda url: {})
    assert len(card["evaluated_rows"]) == len(rows)
    # Missing player fixture/history means explicit blocker, not silently
    # dropped or misrouted as an unknown MLB game market.
    assert all(x.get("status") == "NO_MODEL_OR_MARKET" for x in card["evaluated_rows"])
    assert all("NO_VERIFIED_MODEL_FOR_THIS_MARKET" not in (x.get("reason") or "")
               for x in card["evaluated_rows"])
    expected = {"BATTER_BB", "BATTER_K", "SINGLES", "DOUBLES", "HITS_RUNS_RBIS"}
    assert expected <= set(card["mlb_full_board"]["input_coverage"]["supplied_markets"])


def test_pending_capabilities_do_not_change_adjustments():
    # Run Stage 1 with the same fixtures used by the existing suite.
    observed = datetime(2026, 10, 11, 18, 0, tzinfo=timezone.utc)
    report = stage.stage_games([mlb_row()], now=observed,
                               getter=FakeGetter(mlb_mapping()))[0]
    by_name = {}
    for factor in report["factors"]:
        by_name.setdefault(factor["factor"], []).append(factor)
    assert by_name["lineups_usage"][0]["status"] == "PENDING_VALIDATION"
    assert "not verified" in by_name["lineups_usage"][0]["reason"].lower().replace("_", " ")
    assert by_name["bullpen"][0]["status"] in {"PENDING_VALIDATION", "NOT_WIRED"}
    assert by_name["statcast"][0]["status"] in {"PENDING_VALIDATION", "NOT_WIRED"}
    assert not set(report["adjustments"]).intersection(
        {"bullpen_adj", "statcast_adj", "lineup_adj"})
