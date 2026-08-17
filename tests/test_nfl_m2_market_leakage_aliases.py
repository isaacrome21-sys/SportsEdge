import pytest


def _source(**overrides):
    row = {
        "feature_asof_ts": "2026-09-10T15:00:00+00:00",
        "game_start_ts": "2026-09-10T20:00:00+00:00",
        "qb_id": "qb-1",
        "off_epa": 0.10,
        "def_epa": -0.03,
        "opp_off_epa": 0.02,
        "opp_def_epa": -0.01,
        "prior_weight": 0.4,
        "pass_epa": 0.12,
        "rush_epa": 0.01,
        "pressure_for": 0.33,
        "pressure_allowed": 0.29,
        "success_rate": 0.46,
        "explosive_rate": 0.11,
        "rest_diff_days": 1,
        "travel_miles": 420,
        "timezone_crossings": 1,
        "short_week": 0,
        "bye_week": 0,
        "wind_mph": 8,
        "roof_closed": 0,
        "qb_adjustment": 1.8,
        "prior_efficiency": 0.05,
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize("bad_key", [
    "home_spread",
    "away_spread",
    "consensus_spread",
    "market_spread",
    "closing_spread",
    "market_total",
    "consensus_total",
    "closing_total",
    "market_implied_probability",
    "consensus_implied_prob",
    "sportsbook_price",
    "book_price",
    "closing_odds",
])
def test_market_aliases_are_rejected_from_m2(bad_key):
    from sportsedge.sports.nfl.m2 import build_nfl_m2_features

    with pytest.raises(ValueError, match="M2_MARKET_DATA_PROHIBITED"):
        build_nfl_m2_features(_source(meta={bad_key: 1.0}))


def test_legitimate_football_fields_are_not_false_positives():
    from sportsedge.sports.nfl.m2 import build_nfl_m2_features

    features = build_nfl_m2_features(_source(meta={"offensive_line_continuity": 0.8, "total_yards_prior": 367.0}))
    assert features["qb_id"] == "qb-1"
