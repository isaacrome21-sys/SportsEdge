from sportsedge.mlb_context_model_features import (
    MLBContextFeatureError,
    attach_context_features,
    context_model_features,
)

def _bundle():
    return {
        "game_pk": 123, "as_of_utc": "2026-10-06T18:00:00+00:00", "payload_sha256": "abc",
        "starters": {"status": "AVAILABLE", "probable_pitchers": {"away": {"player_id": 11}, "home": {"player_id": 22}}},
        "lineups": {"status": "AVAILABLE", "complete_by_side": {"away": True, "home": True}},
        "injuries_scratches": {"status": "AVAILABLE"},
        "umpire": {"status": "AVAILABLE", "home_plate_games": 40},
        "statcast": {"status": "AVAILABLE", "bound_pitcher_count": 2, "bound_hitter_count": 18},
        "park_venue": {"status": "AVAILABLE", "venue_id": 7, "roof_type": "Open", "turf_type": "Grass"},
        "weather_roof": {"status": "AVAILABLE", "temperature": 76, "wind_speed": 10, "precip_probability_pct": 0},
        "bullpen_workload": {"status": "AVAILABLE", "teams": {"away": {"bullpen_pitches_24h": 30}, "home": {"bullpen_pitches_24h": 44}}},
        "hybrid_dk": {"quotes": [{"american_odds": -110}]},
    }

def test_bridge_is_price_blind_and_deterministic():
    one = context_model_features(_bundle())
    changed = _bundle()
    changed["hybrid_dk"] = {"quotes": [{"american_odds": 250}]}
    two = context_model_features(changed)
    assert one == two
    assert one["price_blind"] is True
    assert one["features"]["temperature_f"] == 76.0
    assert one["features"]["away_starter_id"] == 11

def test_explicit_price_lane_fails_closed():
    bundle = _bundle()
    bundle["sportsbook"] = {"price": -110}
    try:
        context_model_features(bundle)
    except MLBContextFeatureError as exc:
        assert "sportsbook price lane" in str(exc)
    else:
        raise AssertionError("expected fail closed")

def test_attach_preserves_existing_model_fields():
    row = {"away_mean_runs": 4.2, "home_mean_runs": 3.8}
    out = attach_context_features(row, _bundle())
    assert out["away_mean_runs"] == 4.2
    assert out["home_mean_runs"] == 3.8
    assert out["pregame_context_price_blind"] is True
    assert out["pregame_context_version"] == "mlb_context_model_features_v1"

