from __future__ import annotations

from sportsedge.mlb_pregame_feature_adapter import adapt_pregame_bundle


def test_derived_environment_populates_physical_values_without_promoting_readiness():
    bundle = {
        "game_pk": 999005,
        "as_of_utc": "2026-09-22T22:00:00+00:00",
        "weather_roof": {
            "roof_state": "UNKNOWN",
            "forecast": {
                "temperature": 68,
                "wind_speed": "9 mph",
                "wind_direction": "SW",
                "relative_humidity_pct": 65,
                "precip_probability_pct": 15,
            },
        },
        "environment_derived": {
            "status": "AVAILABLE",
            "source": "NWS_GRID_DERIVED_MLB_ENVIRONMENT",
            "source_weather_sha256": "weather-sha",
            "promotion_status": "RESEARCH_ONLY_UNTIL_TEMPORAL_VALIDATION",
            "values": {
                "temperature_f": 68.0,
                "relative_humidity_pct": 65.0,
                "air_density_kg_m3": 1.19,
                "wind_speed_mph": 9.2,
                "wind_direction_degrees": 225.0,
                "precip_probability_pct": 15.0,
                "wind_out_component_mph": None,
                "wind_in_component_mph": None,
                "delay_risk": None,
                "roof_state": "UNKNOWN",
            },
        },
        "hybrid_dk": {
            "quotes": [{"market": "TOTAL", "line": 8.5, "price": -110}],
        },
    }
    adapted = adapt_pregame_bundle(bundle)
    env = adapted["family_evaluation"]["environment"]
    values = env["values"]

    assert values["temperature"] == 68.0
    assert values["wind_speed"] == 9.2
    assert values["wind_direction"] == 225.0
    assert values["humidity"] == 65.0
    assert values["air_density"] == 1.19
    assert values["precip_probability"] == 15.0
    assert values["wind_out_component"] is None
    assert values["wind_in_component"] is None
    assert env["ready"] is False
    assert "park_hr_factor" in env["missing_fields"]
    assert "wind_out_component" in env["missing_fields"]
    assert "delay_risk" in env["missing_fields"]
    assert "roof_state" in env["missing_fields"]
    assert adapted["market_price_data_present"] is True
    assert "hybrid_dk" in adapted["excluded_from_predictive_context"]
    assert adapted["model_p_eligible"] is False
