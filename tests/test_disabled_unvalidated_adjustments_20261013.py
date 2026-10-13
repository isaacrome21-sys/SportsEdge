"""Owner ruling (Oct 13, 2026): rest_schedule, the ERA-based
starting-pitcher adjustment, and recent_form are DISABLED in the
canonical pricing path until each demonstrates incremental value in
the harness against the retained baseline (team-strength ratings +
static home advantage) and the market.

These tests prove, per adjustment:
  * the priced contribution is exactly zero (score means identical
    with and without a nonzero verified adjustment), and
  * collection/research reporting is intact (declared values are still
    computed and visible in the factor audit, with the disabled state
    labeled DISABLED_PENDING_INCREMENTAL_VALUE).
"""
import importlib.util
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_harness_spec = importlib.util.spec_from_file_location(
    "prepricing_harness", Path(__file__).parent / "test_prepricing_ingestion.py")
harness = importlib.util.module_from_spec(_harness_spec)
_harness_spec.loader.exec_module(harness)

from artifacts import free_models
from sportsedge.prepricing import factor_ingestion as fi

DISABLED = fi.DISABLED_PENDING_INCREMENTAL_VALUE
NOW = harness.NOW
CALC_NOW = datetime(2026, 10, 11, 18, 0, tzinfo=timezone.utc)


def _factors(stage, name):
    return [f for f in stage["factors"] if f["factor"] == name]


# ---------------------------------------------------------------- stage gate

def test_mlb_stage_zeroes_pitcher_and_rest_but_reports_declared_values():
    (stage,) = fi.stage_games(
        [harness.mlb_row()], now=NOW,
        getter=harness.FakeGetter(harness.mlb_mapping()))
    assert stage["blocked"] is False
    pitchers = _factors(stage, "starting_pitcher")
    assert len(pitchers) == 2
    for f in pitchers:
        assert f["status"] == DISABLED
        assert set(f["adjustments"].values()) == {0.0}
        assert "PRICING_CONTRIBUTION_ZERO" in f["reason"]
    reasons = " ".join(f["reason"] for f in pitchers)
    assert "ERA_2.5" in reasons and "ERA_3.0" in reasons  # research values
    assert stage["adjustments"]["home_pitcher_adj"] == 0.0
    assert stage["adjustments"]["away_pitcher_adj"] == 0.0
    (rest,) = _factors(stage, "rest_schedule")
    assert rest["status"] == DISABLED
    assert rest["adjustments"] == {"rest_diff_adj": 0.0}
    assert "DECLARED_DIFF_ADJ_" in rest["reason"]
    assert stage["adjustments"]["rest_diff_adj"] == 0.0
    (form,) = _factors(stage, "recent_form")
    assert form["status"] == DISABLED


def test_nfl_stage_marks_rest_and_recent_form_disabled():
    (stage,) = fi.stage_games(
        [harness.nfl_row()], now=NOW,
        getter=harness.FakeGetter(harness.nfl_mapping()))
    (rest,) = _factors(stage, "rest_schedule")
    assert rest["status"] == DISABLED
    assert rest["adjustments"] == {"rest_diff_adj": 0.0}
    # Declared NFL differential in this fixture is 0.12 (8.0d vs 7.0d):
    # still reported for research, priced at zero.
    assert "DECLARED_DIFF_ADJ_0.12" in rest["reason"]
    assert stage["adjustments"]["rest_diff_adj"] == 0.0
    (form,) = _factors(stage, "recent_form")
    assert form["status"] == DISABLED


def test_collection_math_still_computes_declared_values():
    # The disable is a pricing gate, not a collection change: the
    # declared heuristic still computes nonzero research values.
    assert fi.starter_suppression_adjustment(2.50, 150.0, 25) != 0.0
    padj, pfactors, blocked, _ = fi.mlb_pitcher_adjustments(
        harness.FakeGetter(harness.mlb_mapping()),
        game_date=date(2026, 10, 12),
        home={"abbr": "MIL", "name": "Milwaukee Brewers"},
        away={"abbr": "LAD", "name": "Los Angeles Dodgers"},
        season=2026,
        kickoff=datetime(2026, 10, 12, 20, 10, tzinfo=timezone.utc))
    assert blocked is False
    assert padj["home_pitcher_adj"] != 0.0
    assert padj["away_pitcher_adj"] != 0.0
    assert all(f["status"] == "USED" for f in pfactors)


# --------------------------------------------------------------- engine gate

def _lane_a_means(result):
    la = result["pricing_lanes"]["lane_a_independent"]
    return la["home_mean"], la["away_mean"]


def _nfl_row():
    return {"sport": "NFL", "market": "ML", "side": "HOME",
            "away": "Buffalo Bills", "home": "Los Angeles Rams",
            "odds": -110, "kickoff": "2026-10-12T17:00:00Z",
            "quote_captured_at": "2026-10-11T17:59:00Z"}


def _mlb_row():
    return {"sport": "MLB", "market": "TOTAL", "side": "OVER", "line": 8.5,
            "away": "Los Angeles Dodgers", "home": "Milwaukee Brewers",
            "odds": -110, "kickoff": "2026-10-12T20:10:00Z",
            "quote_captured_at": "2026-10-11T17:59:00Z"}


def _verified(adjustments):
    return {"adjustments": adjustments, "source": "TEST",
            "verification_status": "VERIFIED"}


def test_engine_recent_form_and_rest_contribute_zero():
    base = free_models.calculate(_nfl_row(), None, CALC_NOW,
                                 auto_context=False)
    loaded = free_models.calculate(
        _nfl_row(), None, CALC_NOW, auto_context=False,
        prepricing_adjustments=_verified(
            {"home_form": 1.5, "away_form": -1.5, "rest_diff_adj": 0.6}))
    assert _lane_a_means(loaded) == _lane_a_means(base)
    # Retained baseline only: league prior + static HFA, no ratings
    # (no-fetch mode), no form, no rest.
    prior, _, _, hfa = free_models.PRIORS["NFL"]
    assert _lane_a_means(base) == pytest.approx((prior + hfa / 2,
                                                 prior - hfa / 2))
    # Research values are still carried in context, and the gate is
    # disclosed on the priced row.
    assert loaded["context"]["home_form"] == 1.5
    assert loaded["context"]["rest_diff_adj"] == 0.6
    notes = " ".join(loaded["context_notes"])
    assert "RECENT_FORM_DISABLED_PENDING_INCREMENTAL_VALUE" in notes
    assert "REST_DIFF_ADJ_DISABLED_PENDING_INCREMENTAL_VALUE" in notes


def _nba_row(**extra):
    row = {"sport": "NBA", "market": "ML", "side": "HOME",
           "away": "New York Knicks", "home": "Boston Celtics",
           "odds": -110, "kickoff": "2026-10-12T17:00:00Z",
           "quote_captured_at": "2026-10-11T17:59:00Z"}
    row.update(extra)
    return row


def test_engine_nba_rest_adj_contributes_zero():
    # Owner ruling extended on PR #2120: the NBA rest adjustment is
    # disabled in every canonical pricing path regardless of key name.
    base = free_models.calculate(_nba_row(), None, CALC_NOW,
                                 auto_context=False)
    loaded = free_models.calculate(
        _nba_row(), None, CALC_NOW, auto_context=False,
        prepricing_adjustments=_verified({"rest_adj": 3.0}))
    assert _lane_a_means(loaded) == _lane_a_means(base)
    assert loaded["estimate_p"] == base["estimate_p"]
    # Retained baseline only: league prior + static HFA (no ratings in
    # no-fetch mode); the rest value changes nothing.
    prior, _, _, hfa = free_models.PRIORS["NBA"]
    assert _lane_a_means(base) == pytest.approx((prior + hfa / 2,
                                                 prior - hfa / 2))
    # Research retention: the value is still carried in context, and
    # the gate is disclosed on the priced row.
    assert loaded["context"]["rest_adj"] == 3.0
    assert "REST_ADJ_DISABLED_PENDING_INCREMENTAL_VALUE" in \
        " ".join(loaded["context_notes"])


def test_engine_nba_rest_adj_manual_override_cannot_reactivate():
    # The disable holds however the value arrives: a flagged manual
    # context override (the only way rest_adj reaches an NBA row in
    # practice) must not reactivate the factor.
    zero = free_models.calculate(
        _nba_row(context={"rest_adj": 0.0}), None, CALC_NOW,
        auto_context=False, allow_manual_context=True)
    loaded = free_models.calculate(
        _nba_row(context={"rest_adj": 4.0}), None, CALC_NOW,
        auto_context=False, allow_manual_context=True)
    assert _lane_a_means(loaded) == _lane_a_means(zero)
    assert loaded["estimate_p"] == zero["estimate_p"]
    assert loaded["context"]["rest_adj"] == 4.0
    assert loaded["context_provenance"]["rest_adj"] == "USER_SUPPLIED_MANUAL"
    assert "REST_ADJ_DISABLED_PENDING_INCREMENTAL_VALUE" in \
        " ".join(loaded["context_notes"])


def test_engine_pitcher_and_rest_contribute_zero_mlb():
    base = free_models.calculate(_mlb_row(), None, CALC_NOW,
                                 auto_context=False)
    loaded = free_models.calculate(
        _mlb_row(), None, CALC_NOW, auto_context=False,
        prepricing_adjustments=_verified(
            {"home_pitcher_adj": -1.0, "away_pitcher_adj": 0.8,
             "rest_diff_adj": 0.25}))
    assert _lane_a_means(loaded) == _lane_a_means(base)
    prior, _, _, hfa = free_models.PRIORS["MLB"]
    assert _lane_a_means(base) == pytest.approx((prior + hfa / 2,
                                                 prior - hfa / 2))
    assert loaded["context"]["home_pitcher_adj"] == -1.0
    notes = " ".join(loaded["context_notes"])
    assert "PITCHER_ADJ_DISABLED_PENDING_INCREMENTAL_VALUE" in notes
    assert "REST_DIFF_ADJ_DISABLED_PENDING_INCREMENTAL_VALUE" in notes
