from sportsedge.sports.cfb.candidate_families import (
    materialize_candidate_row,
)

KEYS = (
    "off_ppa_rush","off_ppa_dropback","def_ppa_rush_allowed","def_ppa_dropback_allowed",
    "off_success_rate","def_success_rate_allowed","standard_down_ppa","passing_down_success_rate",
    "eckel_rate","points_per_eckel","points_per_drive","net_field_position","explosive_rate",
)

def metric(value, *, games=0):
    out = {k: float(value) for k in KEYS}
    out.update({"season": 2025, "through_week": 4, "sample_source": "CURRENT_SEASON_PRIOR_WEEKS", "games_in_sample": games})
    return out

def row(games=2):
    prior = metric(10.0, games=games)
    current = metric(20.0, games=games)
    return {
        "season": 2026, "week": 5,
        "home_prior_metrics": dict(prior), "away_prior_metrics": dict(prior),
        "home_current_metrics": dict(current), "away_current_metrics": dict(current),
        "home_metrics": dict(current), "away_metrics": dict(current),
    }

def test_reliability_switches_at_three_games():
    low = materialize_candidate_row("RELIABILITY_WEIGHTED_HARD_SWITCH", row(2), constants={"min_current_games": 3})
    high = materialize_candidate_row("RELIABILITY_WEIGHTED_HARD_SWITCH", row(3), constants={"min_current_games": 3})
    assert low["home_metrics"]["off_ppa_rush"] == 10.0
    assert high["home_metrics"]["off_ppa_rush"] == 20.0

def test_prior_current_blend_uses_frozen_four_game_prior():
    out = materialize_candidate_row("PRIOR_CURRENT_BLEND", row(4), constants={"prior_equivalent_games": 4.0})
    assert out["home_metrics"]["off_ppa_rush"] == 15.0

def test_games_in_sample_feature_caps_at_one():
    out = materialize_candidate_row("GAMES_IN_SAMPLE_FEATURE", row(20), constants={"games_in_sample_cap": 12, "normalization_divisor": 12})
    assert out["home_games_in_sample_feature"] == 1.0
    assert out["away_games_in_sample_feature"] == 1.0

def test_candidate_transforms_reject_market_data():
    bad = row(4)
    bad["closing_line"] = -3.5
    try:
        materialize_candidate_row("PRIOR_CURRENT_BLEND", bad, constants={"prior_equivalent_games": 4.0})
    except ValueError as exc:
        assert "MARKET_DATA_PROHIBITED" in str(exc)
    else:
        raise AssertionError("market data must fail closed")
