"""Owner-disables parity in the independently routed Phase 7 market pricer.

No network, archived odds, historical replays, or authority promotion.
These guard the key-name seam where Phase 7 kept using ERA/form even after
canonical free_models disabled their price contributions.
"""
from datetime import datetime, timedelta, timezone

import pytest

from artifacts.free_models import PRIORS
from sportsedge.market_coverage import _base_means, price_coverage_row


NOW = datetime(2026, 10, 13, 13, 0, tzinfo=timezone.utc)
START = (NOW + timedelta(days=2)).isoformat()


def _row(sport, **extra):
    row = {
        "sport": sport,
        "away": "Away Example",
        "home": "Home Example",
        "kickoff": START,
        "market": "SPREAD_2Q" if sport != "MLB" else "ML_3WAY",
        "side": "HOME",
        "line": -0.5 if sport != "MLB" else None,
        "odds": -110,
    }
    row.update(extra)
    return row


def _mean(row):
    return _base_means(row, now=NOW, auto_context=False)


@pytest.mark.parametrize("sport,disables", [
    ("MLB", {"home_pitcher_adj": 5.0, "away_pitcher_adj": -4.0}),
    ("NFL", {"home_form": 5.0, "away_form": -4.0}),
    ("CFB", {"home_form": 5.0, "away_form": -4.0}),
])
def test_disabled_factors_are_visible_but_cannot_change_means(sport, disables):
    base = _mean(_row(sport))
    modified = _mean(_row(sport, context=disables))
    assert (modified["home_mean"], modified["away_mean"]) == (
        base["home_mean"], base["away_mean"])
    assert all(modified["context"][k] == v for k, v in disables.items())
    assert "DISABLED_PENDING_INCREMENTAL_VALUE" in " ".join(modified["context_notes"])


@pytest.mark.parametrize("sport", ["NFL", "CFB"])
def test_injury_and_ratings_remain_active_while_form_is_disabled(sport):
    row = _row(sport, context={
        "home_rating": 1.1, "away_rating": -0.6,
        "home_injury_pts": -2.0, "away_injury_pts": -0.5,
        "home_form": 4.0, "away_form": -4.0,
        "weather_total_adj": -1.0,
    })
    result = _mean(row)
    base, _, _, hfa = PRIORS[sport]
    assert result["home_mean"] == pytest.approx(base + hfa/2 + 1.1 - 2.0 - 0.5)
    assert result["away_mean"] == pytest.approx(base - hfa/2 - 0.6 - 0.5 - 0.5)


def test_mlb_rating_and_weather_retained_while_pitcher_era_disabled():
    row = _row("MLB", context={
        "home_rating": 0.3, "away_rating": -0.2,
        "home_pitcher_adj": 4.0, "away_pitcher_adj": -3.0,
        "weather_total_adj": -0.8,
    })
    result = _mean(row)
    base, _, _, hfa = PRIORS["MLB"]
    assert result["home_mean"] == pytest.approx(base + hfa/2 + .3 - .4)
    assert result["away_mean"] == pytest.approx(base - hfa/2 - .2 - .4)


@pytest.mark.parametrize("sport,disables", [
    ("NFL", {"home_form": 2.5, "away_form": -2.5}),
    ("CFB", {"home_form": 2.5, "away_form": -2.5}),
])
def test_football_period_price_is_independent_of_disabled_recent_form(sport, disables):
    control = price_coverage_row(_row(sport), now=NOW, auto_context=False)
    exposed = price_coverage_row(_row(sport, context=disables),
                                 now=NOW, auto_context=False)
    assert exposed.get("estimate_p") == control.get("estimate_p")
    assert exposed.get("push_p") == control.get("push_p")
    assert exposed["status"] == control["status"]
