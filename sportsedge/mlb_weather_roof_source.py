"""MLB weather/roof context using public venue metadata and NWS forecasts.

Weather is contextual only. Static StatsAPI roofType is preserved, but this module
does not guess whether a retractable roof will actually be open or closed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re
from typing import Any, Callable, Mapping
from urllib.request import Request, urlopen

from .source_lineage import canonical_json_sha256

NWS_BASE = "https://api.weather.gov"
SOURCE = "NWS_MLB_WEATHER_CONTEXT"
SCHEMA_VERSION = "mlb_weather_roof_source_v1"


class MLBWeatherRoofSourceError(RuntimeError):
    pass


def _open_json(url: str, *, opener: Callable = urlopen) -> dict[str, Any]:
    req = Request(url, headers={
        "Accept": "application/geo+json, application/json",
        "User-Agent": "SportsEdge-MLB-Weather/1.0",
    })
    try:
        with opener(req, timeout=30) as response:
            raw = response.read()
    except Exception as exc:
        raise MLBWeatherRoofSourceError(f"WEATHER_FETCH_FAILED:{url}") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise MLBWeatherRoofSourceError("WEATHER_RESPONSE_NOT_JSON") from exc
    if not isinstance(payload, dict):
        raise MLBWeatherRoofSourceError("WEATHER_RESPONSE_NOT_OBJECT")
    return payload


def points_url(latitude: float, longitude: float) -> str:
    return f"{NWS_BASE}/points/{float(latitude):.6f},{float(longitude):.6f}"


def _scheduled_start(live_payload: Mapping[str, Any] | None) -> datetime | None:
    game_data = (live_payload or {}).get("gameData") or {}
    dt = game_data.get("datetime") if isinstance(game_data, Mapping) else {}
    value = dt.get("dateTime") if isinstance(dt, Mapping) else None
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _period_start(period: Mapping[str, Any]) -> datetime | None:
    value = period.get("startTime")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _quantitative_value(value: Any) -> tuple[Any, Any]:
    """Return NWS quantitative value + unit code without inventing conversions."""
    if not isinstance(value, Mapping):
        return None, None
    return value.get("value"), value.get("unitCode")


def select_hourly_period(hourly_payload: Mapping[str, Any], *, target: datetime) -> dict[str, Any] | None:
    props = hourly_payload.get("properties") or {}
    periods = props.get("periods") if isinstance(props, Mapping) else []
    candidates: list[tuple[float, Mapping[str, Any]]] = []
    for period in periods or []:
        if not isinstance(period, Mapping):
            continue
        start = _period_start(period)
        if start is None:
            continue
        candidates.append((abs((start - target).total_seconds()), period))
    if not candidates:
        return None
    _, period = min(candidates, key=lambda item: item[0])
    precip = period.get("probabilityOfPrecipitation") or {}
    if not isinstance(precip, Mapping):
        precip = {}
    humidity, humidity_unit = _quantitative_value(period.get("relativeHumidity"))
    dewpoint, dewpoint_unit = _quantitative_value(period.get("dewpoint"))
    return {
        "start_time": period.get("startTime"),
        "temperature": period.get("temperature"),
        "temperature_unit": period.get("temperatureUnit"),
        "relative_humidity_pct": humidity,
        "relative_humidity_unit": humidity_unit,
        "dewpoint": dewpoint,
        "dewpoint_unit": dewpoint_unit,
        "wind_speed": period.get("windSpeed"),
        "wind_direction": period.get("windDirection"),
        "precip_probability_pct": precip.get("value"),
        "short_forecast": period.get("shortForecast"),
        "is_daytime": period.get("isDaytime"),
    }


def _parse_iso_duration(value: str) -> timedelta | None:
    """Parse the day/hour/minute/second ISO-8601 subset used by NWS validTime."""
    match = re.fullmatch(
        r"P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?",
        str(value or ""),
    )
    if not match:
        return None
    if not any(match.group(name) for name in ("days", "hours", "minutes", "seconds")):
        return None
    return timedelta(
        days=int(match.group("days") or 0),
        hours=int(match.group("hours") or 0),
        minutes=int(match.group("minutes") or 0),
        seconds=float(match.group("seconds") or 0.0),
    )


def _grid_valid_time(value: Any) -> tuple[datetime, datetime | None] | None:
    text = str(value or "").strip()
    if not text:
        return None
    start_text, _, duration_text = text.partition("/")
    try:
        start = datetime.fromisoformat(start_text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if start.tzinfo is None or start.utcoffset() is None:
        return None
    start = start.astimezone(timezone.utc)
    if not duration_text:
        return start, None
    duration = _parse_iso_duration(duration_text)
    return start, (start + duration if duration is not None else None)


def select_grid_value(
    grid_payload: Mapping[str, Any],
    *,
    key: str,
    target: datetime,
) -> dict[str, Any] | None:
    """Select the NWS grid value covering target, otherwise nearest interval start."""
    props = grid_payload.get("properties") or {}
    block = props.get(key) if isinstance(props, Mapping) else None
    if not isinstance(block, Mapping):
        return None
    values = block.get("values")
    if not isinstance(values, list):
        return None
    unit_code = block.get("uom") or block.get("unitCode")
    candidates: list[tuple[float, Mapping[str, Any], datetime, datetime | None]] = []
    target_utc = target.astimezone(timezone.utc)
    for row in values:
        if not isinstance(row, Mapping):
            continue
        interval = _grid_valid_time(row.get("validTime"))
        if interval is None:
            continue
        start, end = interval
        if end is not None and start <= target_utc < end:
            return {
                "value": row.get("value"),
                "unit_code": unit_code,
                "valid_time": row.get("validTime"),
                "selection": "CONTAINS_TARGET",
            }
        candidates.append((abs((start - target_utc).total_seconds()), row, start, end))
    if not candidates:
        return None
    _, row, _, _ = min(candidates, key=lambda item: item[0])
    return {
        "value": row.get("value"),
        "unit_code": unit_code,
        "valid_time": row.get("validTime"),
        "selection": "NEAREST_START",
    }


def select_grid_context(grid_payload: Mapping[str, Any], *, target: datetime) -> dict[str, Any]:
    keys = (
        "surfacePressure",
        "temperature",
        "relativeHumidity",
        "dewpoint",
        "windSpeed",
        "windDirection",
        "probabilityOfPrecipitation",
    )
    return {key: select_grid_value(grid_payload, key=key, target=target) for key in keys}


def acquire_weather_roof_context(
    *,
    game_pk: int,
    as_of: datetime,
    park_venue: Mapping[str, Any] | None,
    live_payload: Mapping[str, Any] | None = None,
    opener: Callable = urlopen,
    points_payload: Mapping[str, Any] | None = None,
    hourly_payload: Mapping[str, Any] | None = None,
    grid_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    venue = (park_venue or {}).get("venue") or {}
    if not isinstance(venue, Mapping):
        venue = {}
    latitude = venue.get("latitude")
    longitude = venue.get("longitude")
    roof_type = venue.get("roof_type")
    target = _scheduled_start(live_payload) or as_of.astimezone(timezone.utc)
    errors: list[str] = []
    point_url: str | None = None
    forecast_hourly_url: str | None = None
    forecast_grid_data_url: str | None = None
    forecast: dict[str, Any] | None = None
    grid_context: dict[str, Any] | None = None

    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError):
        lat = lon = None

    if lat is not None and lon is not None:
        point_url = points_url(lat, lon)
        point_data: Mapping[str, Any] | None = points_payload
        if point_data is None:
            try:
                point_data = _open_json(point_url, opener=opener)
            except MLBWeatherRoofSourceError as exc:
                errors.append(str(exc))
        props = (point_data or {}).get("properties") or {}
        if isinstance(props, Mapping):
            hourly_value = props.get("forecastHourly")
            grid_value = props.get("forecastGridData")
            if hourly_value:
                forecast_hourly_url = str(hourly_value)
            if grid_value:
                forecast_grid_data_url = str(grid_value)

        hour_data: Mapping[str, Any] | None = hourly_payload
        if hour_data is None and forecast_hourly_url:
            try:
                hour_data = _open_json(forecast_hourly_url, opener=opener)
            except MLBWeatherRoofSourceError as exc:
                errors.append(str(exc))
        if hour_data is not None:
            forecast = select_hourly_period(hour_data, target=target)

        grid_data: Mapping[str, Any] | None = grid_payload
        if grid_data is None and forecast_grid_data_url:
            try:
                grid_data = _open_json(forecast_grid_data_url, opener=opener)
            except MLBWeatherRoofSourceError as exc:
                errors.append(str(exc))
        if grid_data is not None:
            grid_context = select_grid_context(grid_data, target=target)

    if forecast is not None or grid_context is not None:
        status = "AVAILABLE"
    elif lat is None or lon is None:
        status = "UNAVAILABLE_NO_COORDINATES"
    else:
        status = "UNAVAILABLE"

    payload = {
        "schema_version": SCHEMA_VERSION,
        "game_pk": int(game_pk),
        "as_of_utc": as_of.astimezone(timezone.utc).isoformat(),
        "scheduled_start_utc": target.isoformat(),
        "source": SOURCE,
        "venue_id": venue.get("venue_id"),
        "roof_type": roof_type,
        "roof_state": "UNKNOWN",
        "roof_state_reason": "STATIC_VENUE_METADATA_DOES_NOT_PROVE_GAME_DAY_ROOF_STATE",
        "points_url": point_url,
        "forecast_hourly_url": forecast_hourly_url,
        "forecast_grid_data_url": forecast_grid_data_url,
        "forecast": forecast,
        "grid": grid_context,
        "errors": errors,
        "status": status,
        "model_p_eligible": False,
    }
    payload["payload_sha256"] = canonical_json_sha256(payload)
    return payload
