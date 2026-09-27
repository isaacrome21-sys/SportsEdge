from __future__ import annotations

from datetime import datetime, timezone

from sportsedge.mlb_weather_roof_source import (
    acquire_weather_roof_context,
    select_hourly_period,
)


def _hourly() -> dict:
    return {
        "properties": {
            "periods": [
                {
                    "startTime": "2026-09-22T19:00:00-05:00",
                    "temperature": 71,
                    "temperatureUnit": "F",
                    "relativeHumidity": {"unitCode": "wmoUnit:percent", "value": 64},
                    "dewpoint": {"unitCode": "wmoUnit:degC", "value": 14.5},
                    "windSpeed": "8 mph",
                    "windDirection": "SW",
                    "probabilityOfPrecipitation": {"unitCode": "wmoUnit:percent", "value": 20},
                    "shortForecast": "Partly Cloudy",
                    "isDaytime": False,
                },
                {
                    "startTime": "2026-09-22T20:00:00-05:00",
                    "temperature": 68,
                    "temperatureUnit": "F",
                    "relativeHumidity": {"unitCode": "wmoUnit:percent", "value": 70},
                    "dewpoint": {"unitCode": "wmoUnit:degC", "value": 15.0},
                    "windSpeed": "6 mph",
                    "windDirection": "SSW",
                    "probabilityOfPrecipitation": {"unitCode": "wmoUnit:percent", "value": 10},
                    "shortForecast": "Mostly Clear",
                    "isDaytime": False,
                },
            ]
        }
    }


def test_select_hourly_period_preserves_humidity_and_dewpoint_without_conversion():
    target = datetime(2026, 9, 23, 0, 10, tzinfo=timezone.utc)
    period = select_hourly_period(_hourly(), target=target)
    assert period is not None
    assert period["temperature"] == 71
    assert period["relative_humidity_pct"] == 64
    assert period["relative_humidity_unit"] == "wmoUnit:percent"
    assert period["dewpoint"] == 14.5
    assert period["dewpoint_unit"] == "wmoUnit:degC"
    assert period["wind_speed"] == "8 mph"
    assert period["wind_direction"] == "SW"


def test_acquire_weather_context_with_injected_nws_payload_is_network_free_and_context_only():
    as_of = datetime(2026, 9, 22, 22, 0, tzinfo=timezone.utc)
    park = {
        "venue": {
            "venue_id": 17,
            "latitude": 41.95,
            "longitude": -87.65,
            "roof_type": "Open",
        }
    }
    live = {"gameData": {"datetime": {"dateTime": "2026-09-23T00:05:00Z"}}}
    points = {"properties": {"forecastHourly": "https://api.weather.gov/gridpoints/LOT/1,1/forecast/hourly"}}
    result = acquire_weather_roof_context(
        game_pk=999005,
        as_of=as_of,
        park_venue=park,
        live_payload=live,
        points_payload=points,
        hourly_payload=_hourly(),
    )
    assert result["status"] == "AVAILABLE"
    assert result["forecast"]["relative_humidity_pct"] == 64
    assert result["forecast"]["dewpoint"] == 14.5
    assert result["roof_state"] == "UNKNOWN"
    assert result["model_p_eligible"] is False
    assert result["payload_sha256"]
