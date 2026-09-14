"""Strict public Open-Meteo forecast adapter; no historical PIT authority.

API contract: https://open-meteo.com/en/docs
Upstream project: https://github.com/open-meteo/open-meteo
Forecast data attribution: Open-Meteo, CC BY 4.0. This is an original API
adapter; no upstream server implementation or model weights are copied.
"""
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping
from urllib.parse import urlencode

FORECAST_ROOT = "https://api.open-meteo.com/v1/forecast"


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not isfinite(float(value)):
        raise ValueError("WEATHER_FORECAST_NUMBER_INVALID:"+name)
    return float(value)


def forecast_url(latitude: float, longitude: float, start: datetime) -> str:
    lat, lon = _number(latitude, "latitude"), _number(longitude, "longitude")
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("WEATHER_FORECAST_COORDINATES_INVALID")
    if start.tzinfo is None or start.utcoffset() is None:
        raise ValueError("WEATHER_FORECAST_TIMEZONE_REQUIRED")
    day = start.astimezone(timezone.utc).date().isoformat()
    return FORECAST_ROOT+"?"+urlencode({
        "latitude": lat, "longitude": lon,
        "hourly": "temperature_2m,wind_speed_10m,precipitation_probability",
        "temperature_unit": "fahrenheit", "wind_speed_unit": "mph",
        "timezone": "UTC", "timeformat": "unixtime", "start_date": day, "end_date": day,
    })


def kickoff_hour_forecast(payload: Mapping[str, Any], start: datetime) -> dict[str, Any]:
    if start.tzinfo is None or start.utcoffset() is None:
        raise ValueError("WEATHER_FORECAST_TIMEZONE_REQUIRED")
    if payload.get("error") or payload.get("utc_offset_seconds") != 0:
        raise ValueError("WEATHER_FORECAST_RESPONSE_INVALID")
    units, hourly = payload.get("hourly_units"), payload.get("hourly")
    if not isinstance(units, Mapping) or not isinstance(hourly, Mapping):
        raise ValueError("WEATHER_FORECAST_HOURLY_REQUIRED")
    expected = {"time": "unixtime", "temperature_2m": "°F", "wind_speed_10m": "mp/h", "precipitation_probability": "%"}
    if any(units.get(key) != value for key, value in expected.items()):
        raise ValueError("WEATHER_FORECAST_UNITS_MISMATCH")
    times = hourly.get("time")
    if not isinstance(times, list) or any(type(t) is not int for t in times) or len(set(times)) != len(times):
        raise ValueError("WEATHER_FORECAST_TIME_GRID_INVALID")
    hour = int(start.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0).timestamp())
    if hour not in times:
        raise ValueError("WEATHER_FORECAST_KICKOFF_HOUR_MISSING")
    index = times.index(hour)
    values = {}
    for key in expected:
        if key == "time":
            continue
        column = hourly.get(key)
        if not isinstance(column, list) or len(column) != len(times):
            raise ValueError("WEATHER_FORECAST_COLUMN_INVALID:"+key)
        values[key] = _number(column[index], key)
    if values['wind_speed_10m'] < 0 or not 0 <= values['precipitation_probability'] <= 100:
        raise ValueError("WEATHER_FORECAST_RANGE_INVALID")
    return {
        "kind": "FORECAST", "hour_selection": "KICKOFF_HOUR_NO_INTERPOLATION",
        "forecast_valid_at_utc": datetime.fromtimestamp(hour, timezone.utc).isoformat(),
        "temperature_f": values['temperature_2m'], "wind_mph": values['wind_speed_10m'],
        "precipitation_probability_pct": values['precipitation_probability'],
        "attribution": "Open-Meteo (CC BY 4.0)",
        "historical_availability_proven": False,
    }
