from __future__ import annotations

import pytest

from sportsedge.mlb_environment_derived import (
    MLBEnvironmentDerivedError,
    derive_environment_context,
    moist_air_density_kg_m3,
    saturation_vapor_pressure_pa,
)


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
            "windSpeed": {"value": 14.8, "unit_code": "wmoUnit:km_h-1"},
            "windDirection": {"value": 225.0, "unit_code": "wmoUnit:degree_(angle)"},
            "probabilityOfPrecipitation": {"value": 15.0, "unit_code": "wmoUnit:percent"},
        },
    }


def test_saturation_vapor_pressure_is_physical_at_20c():
    value = saturation_vapor_pressure_pa(20.0)
    assert value == pytest.approx(2338.3, rel=0.01)


def test_moist_air_density_uses_actual_pressure():
    low_pressure = moist_air_density_kg_m3(
        temperature_c=20.0,
        relative_humidity_pct=65.0,
        surface_pressure_pa=95_000.0,
    )
    high_pressure = moist_air_density_kg_m3(
        temperature_c=20.0,
        relative_humidity_pct=65.0,
        surface_pressure_pa=101_000.0,
    )
    assert 1.0 < low_pressure < 1.3
    assert high_pressure > low_pressure


def test_derive_environment_normalizes_units_and_computes_air_density():
    result = derive_environment_context(_weather())
    values = result["values"]
    assert result["status"] == "AVAILABLE"
    assert result["required_input_blockers"] == []
    assert values["temperature_c"] == 20.0
    assert values["temperature_f"] == 68.0
    assert values["relative_humidity_pct"] == 65.0
    assert values["surface_pressure_pa"] == 100850.0
    assert values["air_density_kg_m3"] == pytest.approx(1.19, abs=0.04)
    assert values["wind_speed_mph"] == pytest.approx(9.196, abs=0.01)
    assert values["wind_direction_degrees"] == 225.0
    assert values["precip_probability_pct"] == 15.0
    assert values["wind_out_component_mph"] is None
    assert values["wind_in_component_mph"] is None
    assert values["delay_risk"] is None
    assert result["model_p_eligible"] is False
    assert result["promotion_status"] == "RESEARCH_ONLY_UNTIL_TEMPORAL_VALIDATION"


def test_missing_surface_pressure_fails_closed_instead_of_assuming_sea_level():
    weather = _weather()
    weather["grid"] = dict(weather["grid"])
    weather["grid"].pop("surfacePressure")
    result = derive_environment_context(weather)
    assert result["status"] == "INCOMPLETE"
    assert "surface_pressure_pa" in result["required_input_blockers"]
    assert result["values"]["air_density_kg_m3"] is None


def test_invalid_pressure_is_rejected():
    with pytest.raises(MLBEnvironmentDerivedError, match="PRESSURE_OUT_OF_RANGE"):
        moist_air_density_kg_m3(
            temperature_c=20.0,
            relative_humidity_pct=65.0,
            surface_pressure_pa=20_000.0,
        )
