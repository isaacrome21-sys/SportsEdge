"""Regression: disabled factors must not influence direct team-half pricing.

Offline and source-free. Preserve independent ratings, verified football
injuries and weather; zero MLB pitcher and NFL/CFB recent-form price effects.
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sportsedge import team_half_pricing as derivative

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
START = datetime(2026, 10, 15, 20, 0, tzinfo=timezone.utc)
NOTES = [
    "HOME_HISTORY_COUNT:10", "AWAY_HISTORY_COUNT:10",
    "HOME_INJURIES:HEURISTIC_OUT_DOUBTFUL_REPORTED_0_UNKNOWN_COMPLETENESS",
    "AWAY_INJURIES:HEURISTIC_OUT_DOUBTFUL_REPORTED_0_UNKNOWN_COMPLETENESS",
    "WEATHER:INDOOR_VERIFIED",
]
PROVIDER = SimpleNamespace(
    fixture=lambda *args: (None, {"id": "verified-event"}),
    # This focused factor-parity test uses generic non-Illinois teams;
    # #2148 added the independent ID binder to CFB scoring. Stub the
    # directory correctly without altering or bypassing the production gate.
    identify=lambda *args: None,
)


def context(**overrides):
    values = {
        "home_rating": 1.0, "away_rating": -0.5,
        "home_injury_pts": 0.0, "away_injury_pts": 0.0,
        "home_form": 0.0, "away_form": 0.0,
        "home_pitcher_adj": 0.0, "away_pitcher_adj": 0.0,
        "weather_total_adj": 0.0,
    }
    values.update(overrides)
    return values


def scoring(sport, ctx):
    with patch.object(
        derivative.engine, "context_for",
        return_value=(ctx, START, NOTES),
    ):
        return derivative._scoring(
            sport, "Generic Home", "Generic Away",
            START.isoformat(), NOW, PROVIDER,
        )


@pytest.mark.parametrize("sport", ["NFL", "CFB"])
def test_football_recent_form_cannot_change_any_team_half_score_mean(sport):
    baseline = scoring(sport, context())
    poisoned = scoring(sport, context(home_form=15.0, away_form=-15.0))
    assert poisoned[:2] == baseline[:2]
    assert poisoned[6] == baseline[6] == "verified-event"


def test_mlb_pitcher_adjustment_cannot_change_team_half_score_means():
    baseline = scoring("MLB", context())
    poisoned = scoring(
        "MLB", context(home_pitcher_adj=10.0, away_pitcher_adj=-10.0)
    )
    assert poisoned[:2] == baseline[:2]


@pytest.mark.parametrize("sport", ["NFL", "CFB"])
def test_verified_football_injuries_still_affect_expected_score(sport):
    baseline = scoring(sport, context())
    injured = scoring(
        sport, context(home_injury_pts=-1.5, away_injury_pts=-0.75)
    )
    assert injured[0] == pytest.approx(baseline[0] - 1.5)
    assert injured[1] == pytest.approx(baseline[1] - 0.75)


@pytest.mark.parametrize("sport", ["MLB", "NFL", "CFB"])
def test_unchanged_ratings_weather_still_affect_score_means(sport):
    baseline = scoring(sport, context())
    improved = scoring(
        sport, context(home_rating=2.0, away_rating=0.5,
                       weather_total_adj=1.0)
    )
    assert improved[0] == pytest.approx(baseline[0] + 1.5)
    assert improved[1] == pytest.approx(baseline[1] + 1.5)
