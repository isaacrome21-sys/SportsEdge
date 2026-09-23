from __future__ import annotations

import pytest

from sportsedge.mlb_environment_derived import (
    derive_environment_context,
    stadium_wind_components_mph,
)
from sportsedge.mlb_park_venue_source import parse_venue
from sportsedge.mlb_pregame_feature_adapter import adapt_pregame_bundle


def _weather() -> dict:
    return {
        "game_pk": 999005,
        "as_of_utc": "2026-09-22T22:00:00+00:00",
        "scheduled_start_utc": "2026-09-23T00:35:00+00:00",
        "roof_type": "Open",
        "roof_state": "UNKNOWN",
        "payload_sha256": "weather-sha",
        "grid": {
            "surfacePressure": {"value": 100850.0, "unit_code": "wmoUnit:Pa"},
            "temperature": {"value": 20.0, "unit_code": "wmoUnit:degC"},
            "relativeHumidity": {"value": 65.0, "unit_code": "wmoUnit:percent"},
            "dewpoint": {"value": 13.2, "unit_code": "wmoUnit:degC"},
            "windSpeed": {"value": 16.09344, "unit_code": "wmoUnit:km_h-1"},
            "windDirection": {"value": 180.0, "unit_code": "wmoUnit:degree_(angle)"},
            "probabilityOfPrecipitation": {"value": 15.0, "unit_code": "wmoUnit:percent"},
        },
    }


def test_parse_venue_preserves_and_normalizes_statsapi_azimuth():
    parsed = parse_venue({
        "venues": [{
            "id": 17,
            "name": "Example Park",
            "location": {
                "city": "Chicago",
                "defaultCoordinates": {"latitude": 41.95, "longitude": -87.65},
                "azimuthAngle": 370.5,
                "elevation": 595,
            },
            "fieldInfo": {"roofType": "Open", "turfType": "Grass"},
            "timeZone": {"id": "America/Chicago"},
        }]
    })
    assert parsed is not None
    assert parsed["azimuth_angle_degrees"] == 10.5
    assert parsed["azimuth_source_field"] == "location.azimuthAngle"
    assert parsed["elevation_raw"] == 595.0


def test_stadium_wind_projection_respects_meteorological_from_direction():
    out, incoming, signed = stadium_wind_components_mph(
        wind_speed_mph=10.0,
        wind_from_degrees=180.0,
        field_azimuth_degrees=0.0,
    )
    assert out == pytest.approx(10.0, abs=1e-8)
    assert incoming == pytest.approx(0.0, abs=1e-8)
    assert signed == pytest.approx(10.0, abs=1e-8)

    out, incoming, signed = stadium_wind_components_mph(
        wind_speed_mph=10.0,
        wind_from_degrees=0.0,
        field_azimuth_degrees=0.0,
    )
    assert out == pytest.approx(0.0, abs=1e-8)
    assert incoming == pytest.approx(10.0, abs=1e-8)
    assert signed == pytest.approx(-10.0, abs=1e-8)


def test_derived_environment_uses_statsapi_azimuth_when_present():
    park = {
        "payload_sha256": "venue-sha",
        "venue": {"venue_id": 17, "azimuth_angle_degrees": 0.0},
    }
    result = derive_environment_context(_weather(), park)
    assert result["wind_geometry_status"] == "AVAILABLE"
    assert result["source_venue_sha256"] == "venue-sha"
    assert result["values"]["wind_speed_mph"] == pytest.approx(10.0, abs=0.001)
    assert result["values"]["wind_out_component_mph"] == pytest.approx(10.0, abs=0.001)
    assert result["values"]["wind_in_component_mph"] == pytest.approx(0.0, abs=0.001)


def _complete_environment_bundle() -> dict:
    return {
        "game_pk": 999005,
        "park_factors": {
            "status": "AVAILABLE",
            "model_version": "research_pf_v1",
            "values": {
                "park_hr_factor": 1.03,
                "park_hr_factor_lhb": 1.04,
                "park_hr_factor_rhb": 1.02,
                "park_runs_factor": 1.01,
                "park_1b_factor": 0.99,
                "park_2b_3b_factor": 1.02,
            },
        },
        "environment_derived": {
            "status": "AVAILABLE",
            "values": {
                "temperature_f": 68.0,
                "wind_speed_mph": 10.0,
                "wind_direction_degrees": 180.0,
                "wind_out_component_mph": 10.0,
                "wind_in_component_mph": 0.0,
                "relative_humidity_pct": 65.0,
                "air_density_kg_m3": 1.19,
                "precip_probability_pct": 15.0,
                "delay_risk": 0.0,
                "roof_state": "OPEN",
                "dome_state": "NOT_DOME",
            },
        },
    }


def test_complete_environment_stays_blocked_without_explicit_validation():
    bundle = _complete_environment_bundle()
    adapted = adapt_pregame_bundle(bundle)
    env = adapted["family_evaluation"]["environment"]
    assert env["input_complete"] is True
    assert env["ready"] is False
    assert env["missing_fields"] == ()
    assert env["validation_blockers"] == (
        "park_factors",
        "air_density",
        "wind_components",
        "roof_delay_state",
    )

    bundle["environment_feature_validation"] = {
        "park_factors": True,
        "air_density": True,
        "wind_components": True,
        "roof_delay_state": True,
    }
    promoted = adapt_pregame_bundle(bundle)["family_evaluation"]["environment"]
    assert promoted["input_complete"] is True
    assert promoted["validation_blockers"] == ()
    assert promoted["ready"] is True
