from __future__ import annotations

from datetime import datetime, timezone

from sportsedge.mlb_weather_roof_source import (
    acquire_weather_roof_context,
    select_grid_context,
    select_grid_value,
)


def _grid() -> dict:
    return {
        "properties": {
            "surfacePressure": {
                "uom": "wmoUnit:Pa",
                "values": [
                    {"validTime": "2026-09-23T00:00:00+00:00/PT1H", "value": 100850.0},
                    {"validTime": "2026-09-23T01:00:00+00:00/PT1H", "value": 100800.0},
                ],
            },
            "temperature": {
                "uom": "wmoUnit:degC",
                "values": [{"validTime": "2026-09-23T00:00:00+00:00/PT2H", "value": 20.0}],
            },
            "relativeHumidity": {
                "uom": "wmoUnit:percent",
                "values": [{"validTime": "2026-09-23T00:00:00+00:00/PT2H", "value": 65.0}],
            },
            "dewpoint": {
                "uom": "wmoUnit:degC",
                "values": [{"validTime": "2026-09-23T00:00:00+00:00/PT2H", "value": 13.2}],
            },
            "windSpeed": {
                "uom": "wmoUnit:km_h-1",
                "values": [{"validTime": "2026-09-23T00:00:00+00:00/PT2H", "value": 14.8}],
            },
            "windDirection": {
                "uom": "wmoUnit:degree_(angle)",
                "values": [{"validTime": "2026-09-23T00:00:00+00:00/PT2H", "value": 225.0}],
            },
            "probabilityOfPrecipitation": {
                "uom": "wmoUnit:percent",
                "values": [{"validTime": "2026-09-23T00:00:00+00:00/PT2H", "value": 15.0}],
            },
        }
    }


def test_select_grid_value_prefers_interval_covering_target():
    target = datetime(2026, 9, 23, 0, 35, tzinfo=timezone.utc)
    selected = select_grid_value(_grid(), key="surfacePressure", target=target)
    assert selected == {
        "value": 100850.0,
        "unit_code": "wmoUnit:Pa",
        "valid_time": "2026-09-23T00:00:00+00:00/PT1H",
        "selection": "CONTAINS_TARGET",
    }


def test_select_grid_context_preserves_pressure_and_numeric_wind():
    target = datetime(2026, 9, 23, 0, 35, tzinfo=timezone.utc)
    context = select_grid_context(_grid(), target=target)
    assert context["surfacePressure"]["value"] == 100850.0
    assert context["surfacePressure"]["unit_code"] == "wmoUnit:Pa"
    assert context["temperature"]["value"] == 20.0
    assert context["relativeHumidity"]["value"] == 65.0
    assert context["windSpeed"]["value"] == 14.8
    assert context["windDirection"]["value"] == 225.0


def test_acquire_weather_context_uses_injected_grid_data_without_network():
    as_of = datetime(2026, 9, 22, 22, 0, tzinfo=timezone.utc)
    park = {
        "venue": {
            "venue_id": 17,
            "latitude": 41.95,
            "longitude": -87.65,
            "roof_type": "Open",
        }
    }
    live = {"gameData": {"datetime": {"dateTime": "2026-09-23T00:35:00Z"}}}
    points = {
        "properties": {
            "forecastHourly": "https://api.weather.gov/gridpoints/LOT/1,1/forecast/hourly",
            "forecastGridData": "https://api.weather.gov/gridpoints/LOT/1,1",
        }
    }
    hourly = {
        "properties": {
            "periods": [{
                "startTime": "2026-09-23T00:00:00Z",
                "temperature": 68,
                "temperatureUnit": "F",
                "relativeHumidity": {"unitCode": "wmoUnit:percent", "value": 65},
                "dewpoint": {"unitCode": "wmoUnit:degC", "value": 13.2},
                "windSpeed": "9 mph",
                "windDirection": "SW",
                "probabilityOfPrecipitation": {"unitCode": "wmoUnit:percent", "value": 15},
            }]
        }
    }
    result = acquire_weather_roof_context(
        game_pk=999005,
        as_of=as_of,
        park_venue=park,
        live_payload=live,
        points_payload=points,
        hourly_payload=hourly,
        grid_payload=_grid(),
    )
    assert result["status"] == "AVAILABLE"
    assert result["forecast_grid_data_url"] == "https://api.weather.gov/gridpoints/LOT/1,1"
    assert result["grid"]["surfacePressure"]["value"] == 100850.0
    assert result["grid"]["windDirection"]["value"] == 225.0
    assert result["roof_state"] == "UNKNOWN"
    assert result["model_p_eligible"] is False
