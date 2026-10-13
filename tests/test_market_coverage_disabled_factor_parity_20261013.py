"""Regression contract: derivatives cannot re-enable disabled ERA/form adjustments.

Every case is offline. No fixture/lineup acquisition, historical collection,
or market-price/profitability promotion is exercised.
"""
from datetime import datetime, timedelta, timezone

import pytest

from artifacts.free_models import PRIORS
from sportsedge.market_coverage import (
    _base_means,
    price_coverage_row,
)

NOW = datetime(2026, 10, 13, 15, 0, tzinfo=timezone.utc)
KICKOFF = (NOW + timedelta(hours=6)).isoformat()


def _row(sport, *, context=None, market=None, side=None):
    return {
        "sport": sport,
        "away": "Away Test Team",
        "home": "Home Test Team",
        "commence_time": KICKOFF,
        "market": market or ("ML_3WAY" if sport == "MLB" else "SPREAD_1Q"),
        "side": side or "HOME",
        "line": -0.5,
        "odds": -110,
        "context": context or {},
    }


@pytest.mark.parametrize("sport", ["MLB", "NFL", "CFB"])
def test_coverage_means_ignore_owner_disabled_factors(sport):
    base = _base_means(_row(sport), now=NOW, auto_context=False)
    disabled = (
        {"home_pitcher_adj": -2.0, "away_pitcher_adj": 1.5}
        if sport == "MLB"
        else {"home_form": 2.0, "away_form": -1.5}
    )
    active = _base_means(
        _row(sport, context=disabled), now=NOW, auto_context=False)
    assert (base["home_mean"], base["away_mean"]) == (
        active["home_mean"], active["away_mean"])
    assert all(active["context"][key] == val for key, val in disabled.items())
    code = ("PITCHER_ADJ_DISABLED_PENDING_INCREMENTAL_VALUE" if sport == "MLB"
            else "RECENT_FORM_DISABLED_PENDING_INCREMENTAL_VALUE")
    assert code in active["context_notes"]


@pytest.mark.parametrize("sport", ["NFL", "CFB"])
def test_coverage_retains_active_injury_context_while_zeroing_recent_form(sport):
    baseline = _base_means(_row(sport), now=NOW, auto_context=False)
    inputs = {
        "home_injury_pts": -1.5,
        "away_injury_pts": -0.5,
        "home_form": 5.0,
        "away_form": -5.0,
    }
    now = _base_means(_row(sport, context=inputs),
                      now=NOW, auto_context=False)
    assert now["home_mean"] == pytest.approx(baseline["home_mean"] - 1.5)
    assert now["away_mean"] == pytest.approx(baseline["away_mean"] - 0.5)


@pytest.mark.parametrize("sport", ["NFL", "CFB"])
def test_observable_quarter_research_probability_not_changed_by_recent_form(sport):
    # Passing a nonzero manual form field was an exploitable alternate-path
    # method for moving a period probability despite its disabled status.
    base = price_coverage_row(
        _row(sport, market="SPREAD_1Q", side="HOME"),
        now=NOW, auto_context=False)
    form = price_coverage_row(
        _row(sport, market="SPREAD_1Q", side="HOME",
             context={"home_form": 5.0, "away_form": -5.0}),
        now=NOW, auto_context=False)
    if sport == "NFL":
        # Canonical owner ruling: an unfitted quarter fraction must NOT
        # emit a price, even if recent-form changes are disabled.
        for row in (base, form):
            assert row["status"] == "NO_MODEL_OR_MARKET"
            assert row["reason"] == "SIMULATION_ROWS_EMPTY"
            assert row["blocker"] == "NO_ENGINE"
            assert "estimate_p" not in row
            assert "ev_per_dollar" not in row
    else:
        # The CFB research-only quarter path retains its prior behavior.
        assert base["estimate_p"] == form["estimate_p"]
        assert base["ev_per_dollar"] == form["ev_per_dollar"]


def test_research_coverage_retained_baseline_terms():
    for sport in ("MLB", "NFL", "CFB"):
        means = _base_means(_row(sport), now=NOW, auto_context=False)
        base, _, _, hfa = PRIORS[sport]
        assert means["home_mean"] == pytest.approx(base + hfa / 2)
        assert means["away_mean"] == pytest.approx(base - hfa / 2)


def test_unrelated_context_heuristics_are_never_used_to_unlock_failed_market():
    base = price_coverage_row(
        _row("MLB", market="ML_3WAY",
             context={"home_pitcher_adj": 4.5}),
        now=NOW, auto_context=False)
    assert base["status"] == "NO_MODEL_OR_MARKET"
    assert base["reason"] == "COVERAGE_MARKET_FAILED_VALIDATION_NOT_WIRED"
