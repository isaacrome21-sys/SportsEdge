from sportsedge.core.position_matchup import (
    build_positional_matchup_features,
    continuity_weight,
    positional_target_share_oe_allowed,
)
from sportsedge.sports.cfb.m2 import build_cfb_m2_features
from sportsedge.sports.nfl.m2 import build_nfl_m2_features


def test_target_share_over_expected_math():
    out = positional_target_share_oe_allowed(
        {"WR": 0.60, "TE": 0.24, "RB": 0.16},
        {"WR": 0.56, "TE": 0.20, "RB": 0.24},
    )
    assert out == {"WR": 0.04, "TE": 0.04, "RB": -0.08}


def test_new_dc_discount_is_lower_than_same_dc():
    same = continuity_weight(True, 0.80)
    changed = continuity_weight(False, 0.80)
    assert same > changed
    assert 0.0 <= changed <= 1.0


def test_direct_oe_shape_builds_weighted_features():
    out = build_positional_matchup_features({
        "positional_target_share_oe_allowed": {"WR": 0.08, "TE": -0.02, "RB": 0.03},
        "same_defensive_playcaller": False,
        "returning_defensive_starter_share": 0.75,
    })
    assert out["opp_wr_target_share_oe_allowed"] == 0.08
    assert out["opp_te_target_share_oe_allowed"] == -0.02
    assert out["defensive_playcaller_changed"] == 1.0
    assert abs(out["opp_wr_target_share_oe_weighted"]) < 0.08


def _nfl_source():
    return {
        "feature_asof_ts": "2026-08-19T12:00:00+00:00",
        "game_start_ts": "2026-08-20T00:00:00+00:00",
        "qb_id": "QB1",
        "off_epa": 0.12,
        "def_epa": -0.04,
        "opp_off_epa": 0.08,
        "opp_def_epa": -0.02,
        "prior_weight": 0.5,
        "pass_epa": 0.15,
        "rush_epa": 0.01,
        "pressure_for": 0.31,
        "pressure_allowed": 0.27,
        "success_rate": 0.46,
        "explosive_rate": 0.11,
        "rest_diff_days": 0,
        "travel_miles": 350,
        "timezone_crossings": 1,
        "short_week": 0,
        "bye_week": 0,
        "wind_mph": 8,
        "roof_closed": 0,
        "qb_adjustment": 0.03,
        "prior_efficiency": 0.02,
        "positional_target_share_oe_allowed": {"WR": 0.05, "TE": 0.09, "RB": -0.04},
        "same_defensive_playcaller": True,
        "returning_defensive_starter_share": 0.9,
    }


def test_nfl_m2_includes_positional_matchup_features():
    out = build_nfl_m2_features(_nfl_source())
    assert out["opp_te_target_share_oe_allowed"] == 0.09
    assert out["defensive_playcaller_changed"] == 0.0


def test_cfb_m2_includes_positional_matchup_features():
    src = {
        "feature_asof_ts": "2026-08-19T12:00:00+00:00",
        "game_start_ts": "2026-08-20T00:00:00+00:00",
        "off_epa": 0.10,
        "def_epa": -0.03,
        "opp_off_epa": 0.06,
        "opp_def_epa": -0.01,
        "returning_production": 0.68,
        "prior_rating": 7.5,
        "venue_hfa": 2.2,
        "positional_target_share_allowed": {"WR": 0.62, "TE": 0.18, "RB": 0.20},
        "positional_target_share_expected": {"WR": 0.57, "TE": 0.21, "RB": 0.22},
        "same_defensive_playcaller": False,
        "returning_defensive_starter_share": 0.55,
    }
    out = build_cfb_m2_features(src)
    assert abs(out["opp_wr_target_share_oe_allowed"] - 0.05) < 1e-12
    assert abs(out["opp_te_target_share_oe_allowed"] + 0.03) < 1e-12
    assert out["defensive_playcaller_changed"] == 1.0
