"""National Weather Service (api.weather.gov) game-window weather source.

REGISTERED RESEARCH ONLY -- NOT_VALIDATED, zero pricing impact.

This module is the live FEED behind the declared weather thresholds in
``sportsedge.free_factors`` (``weather_total_adjustment`` / ``ingest_weather``).
Those thresholds stay PENDING_VALIDATION: this collector does not activate,
compute, or feed any adjustment, and nothing in the pricing path imports it.
It only normalizes NWS observations and hourly forecasts for a venue
(latitude/longitude) and a game window into a provenance-carrying record.

Source facts (live-probed 2026-10-24): api.weather.gov is a free public
API -- no key, no account; it requires a descriptive User-Agent header.
``/points/{lat,lon}`` resolves the forecast grid, the hourly-forecast URL,
and the observation-station list. Observations carry whole-degree Celsius
temperatures, km/h wind, degree wind direction, and a text description;
precipitation is frequently null (missing, NOT zero).

Fail-closed rules:
  * transport or JSON failure on the points/stations lookups raises
    NWSWeatherSourceError -- no record is fabricated;
  * an observation counts only inside the requested window, never from
    the future relative to retrieval time, and only within
    MAX_OBSERVATION_LAG of the window start -- a stale or missing
    observation yields status UNVERIFIED with the fields null, never an
    interpolated or carried-over value;
  * a measured value whose unit code is not the expected WMO unit is
    treated as missing, never silently reinterpreted;
  * null precipitation stays null.

Venue roof state is NOT modeled: a domed or retractable-roof venue still
returns outdoor weather. Mapping venues to roof behavior is a separate
follow-up (see sportsedge.mlb_weather_roof_source for the MLB-specific
roof/grid context). Any lat/lon works -- NFL/CFB/MLB/NHL venues are just
coordinates to this source.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping
from urllib.request import Request, urlopen

NWS_BASE = "https://api.weather.gov"
SOURCE = "NWS_API_WEATHER_GOV"
SCHEMA_VERSION = "nws_weather_source_v1"
USER_AGENT = "SportsEdge-NWS-Weather/1.0 (research-only; no pricing use)"

STATUS_VERIFIED = "VERIFIED_OBSERVATION"
STATUS_UNVERIFIED = "UNVERIFIED"
REASON_NO_OBSERVATION = "NO_OBSERVATION_IN_WINDOW"
REASON_STALE = "OBSERVATION_STALE_AT_WINDOW_START"

# An observation is evidence about the window start (e.g. kickoff) only if
# it was taken within this lag of it; anything later describes a different
# game state and must not be silently carried back.
MAX_OBSERVATION_LAG = timedelta(minutes=90)
MAX_STATIONS_TRIED = 3
# The observations endpoint paginates newest-first with a cursor, and a
# first page can end before the window start (live-probed 2026-10-24:
# KAUS page 1 stopped at 01:55Z for a 23:30Z-02:30Z window while holding
# a cursor to older reports). Pages are followed, bounded, until the
# window start is covered; selection re-filters by window regardless.
MAX_OBSERVATION_PAGES = 5

_KMH_TO_MPH = 0.621371192237334
_COMPASS16 = (
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
)
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


class NWSWeatherSourceError(RuntimeError):
    """Transport/contract failure; the caller must fail closed."""


def _open_json(url: str, *, opener: Callable = urlopen) -> dict[str, Any]:
    req = Request(url, headers={
        "Accept": "application/geo+json, application/json",
        "User-Agent": USER_AGENT,
    })
    try:
        with opener(req, timeout=30) as response:
            raw = response.read()
    except Exception as exc:
        raise NWSWeatherSourceError(f"WEATHER_FETCH_FAILED:{url}") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise NWSWeatherSourceError("WEATHER_RESPONSE_NOT_JSON") from exc
    if not isinstance(payload, dict):
        raise NWSWeatherSourceError("WEATHER_RESPONSE_NOT_OBJECT")
    return payload


def points_url(latitude: float, longitude: float) -> str:
    return f"{NWS_BASE}/points/{float(latitude):.6f},{float(longitude):.6f}"


def _observations_url(station_id: str, start: datetime, end: datetime) -> str:
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return (f"{NWS_BASE}/stations/{station_id}/observations"
            f"?start={start.strftime(fmt)}&end={end.strftime(fmt)}&limit=500")


def _parse_instant(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _quantity(props: Mapping[str, Any], key: str,
              expected_unit: str) -> float | None:
    """A measured quantity, or None if absent/null/wrong-unit/non-numeric."""
    raw = props.get(key)
    if not isinstance(raw, Mapping):
        return None
    unit = raw.get("unitCode")
    if unit is not None and unit != expected_unit:
        return None
    value = raw.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def compass16(degrees: float | None) -> str | None:
    if degrees is None:
        return None
    return _COMPASS16[int((degrees % 360.0) / 22.5 + 0.5) % 16]


def _c_to_f(celsius: float | None) -> float | None:
    return None if celsius is None else round(celsius * 9.0 / 5.0 + 32.0, 1)


def _kmh_to_mph(kmh: float | None) -> float | None:
    return None if kmh is None else round(kmh * _KMH_TO_MPH, 1)


def normalize_observation(feature: Mapping[str, Any], *,
                          station_id: str,
                          station_name: str | None) -> dict[str, Any] | None:
    """Normalize one NWS observation feature; None if it has no timestamp."""
    props = feature.get("properties")
    if not isinstance(props, Mapping):
        return None
    observed_at = _parse_instant(props.get("timestamp"))
    if observed_at is None:
        return None
    temp_c = _quantity(props, "temperature", "wmoUnit:degC")
    dew_c = _quantity(props, "dewpoint", "wmoUnit:degC")
    wind_kmh = _quantity(props, "windSpeed", "wmoUnit:km_h-1")
    gust_kmh = _quantity(props, "windGust", "wmoUnit:km_h-1")
    wind_deg = _quantity(props, "windDirection", "wmoUnit:degree_(angle)")
    precip_mm = _quantity(props, "precipitationLastHour", "wmoUnit:mm")
    return {
        "station_id": station_id,
        "station_name": station_name,
        "observed_at": observed_at.isoformat(),
        "temperature_f": _c_to_f(temp_c),
        "dewpoint_f": _c_to_f(dew_c),
        "wind_speed_mph": _kmh_to_mph(wind_kmh),
        "wind_gust_mph": _kmh_to_mph(gust_kmh),
        "wind_direction_degrees": wind_deg,
        "wind_compass": compass16(wind_deg),
        "precipitation_last_hour_mm": precip_mm,
        "conditions": props.get("textDescription") or None,
    }


def select_window_observation(features: Any, *, station_id: str,
                              station_name: str | None,
                              window_start: datetime, window_end: datetime,
                              now: datetime) -> tuple[dict[str, Any] | None, str | None]:
    """Pick the in-window observation closest to the window start.

    Returns (observation, None) or (None, reason). Future observations
    (after ``now``) and out-of-window observations never count; the chosen
    observation must sit within MAX_OBSERVATION_LAG of the window start.
    """
    if not isinstance(features, list):
        return None, REASON_NO_OBSERVATION
    best: tuple[timedelta, dict[str, Any], datetime] | None = None
    for feature in features:
        if not isinstance(feature, Mapping):
            continue
        obs = normalize_observation(feature, station_id=station_id,
                                    station_name=station_name)
        if obs is None:
            continue
        observed_at = _parse_instant(obs["observed_at"])
        if observed_at is None or observed_at > now:
            continue
        if not (window_start <= observed_at <= window_end):
            continue
        if obs["temperature_f"] is None and obs["wind_speed_mph"] is None:
            continue
        lag = abs(observed_at - window_start)
        if best is None or lag < best[0]:
            best = (lag, obs, observed_at)
    if best is None:
        return None, REASON_NO_OBSERVATION
    if best[0] > MAX_OBSERVATION_LAG:
        return None, REASON_STALE
    return best[1], None


def _wind_mph_from_forecast(text: Any) -> float | None:
    """NWS hourly windSpeed is text ('5 mph', '5 to 10 mph'); take the max."""
    if not isinstance(text, str):
        return None
    numbers = _NUMBER.findall(text)
    if not numbers:
        return None
    return max(float(n) for n in numbers)


def _fetch_station_observations(station_id: str, *,
                                  window_start: datetime,
                                  window_end: datetime,
                                  opener: Callable) -> list[Any]:
    """All observations the endpoint serves for the window (cursor-walked).

    Pages arrive newest-first. Walking stops when a page's oldest
    observation reaches the window start (older pages cannot hold
    in-window evidence), when no cursor remains, or at
    MAX_OBSERVATION_PAGES. The combined list is NOT trusted as
    window-filtered -- selection re-filters every feature.
    """
    url: str | None = _observations_url(station_id, window_start, window_end)
    features: list[Any] = []
    for _ in range(MAX_OBSERVATION_PAGES):
        if url is None:
            break
        payload = _open_json(url, opener=opener)
        page = payload.get("features")
        if not isinstance(page, list):
            break
        features.extend(page)
        oldest: datetime | None = None
        for feature in page:
            if not isinstance(feature, Mapping):
                continue
            props = feature.get("properties")
            if not isinstance(props, Mapping):
                continue
            instant = _parse_instant(props.get("timestamp"))
            if instant is not None and (oldest is None or instant < oldest):
                oldest = instant
        pagination = payload.get("pagination")
        nxt = pagination.get("next") if isinstance(pagination, Mapping) \
            else None
        url = nxt if isinstance(nxt, str) and nxt else None
        if oldest is not None and oldest <= window_start:
            break
    return features


def normalize_forecast_periods(payload: Mapping[str, Any], *,
                               window_start: datetime,
                               window_end: datetime) -> list[dict[str, Any]]:
    props = payload.get("properties")
    periods = props.get("periods") if isinstance(props, Mapping) else None
    if not isinstance(periods, list):
        return []
    out: list[dict[str, Any]] = []
    for period in periods:
        if not isinstance(period, Mapping):
            continue
        start = _parse_instant(period.get("startTime"))
        end = _parse_instant(period.get("endTime"))
        if start is None or end is None:
            continue
        if not (start < window_end and end > window_start):
            continue
        temp = period.get("temperature")
        if isinstance(temp, bool) or not isinstance(temp, (int, float)):
            temp_f = None
        elif period.get("temperatureUnit") == "C":
            temp_f = _c_to_f(float(temp))
        else:
            temp_f = float(temp)
        pop = period.get("probabilityOfPrecipitation")
        pop_value = pop.get("value") if isinstance(pop, Mapping) else None
        if isinstance(pop_value, bool) or not isinstance(pop_value, (int, float)):
            pop_value = None
        out.append({
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "temperature_f": temp_f,
            "wind_speed_mph": _wind_mph_from_forecast(period.get("windSpeed")),
            "wind_direction": period.get("windDirection") or None,
            "probability_of_precipitation_pct": pop_value,
            "conditions": period.get("shortForecast") or None,
        })
    return out


def game_window_weather(latitude: float, longitude: float, *,
                        window_start: datetime, window_end: datetime,
                        now: datetime | None = None,
                        opener: Callable = urlopen) -> dict[str, Any]:
    """Normalized game-window weather record for a venue (research only).

    ``window_start``/``window_end`` bound the game window (e.g. kickoff to
    expected end). Status is VERIFIED_OBSERVATION only when a station
    observation inside the window, within MAX_OBSERVATION_LAG of the
    window start and not from the future, exists; otherwise UNVERIFIED
    with a named reason and null observation fields.
    """
    if not (-90.0 <= float(latitude) <= 90.0):
        raise NWSWeatherSourceError("INVALID_LATITUDE")
    if not (-180.0 <= float(longitude) <= 180.0):
        raise NWSWeatherSourceError("INVALID_LONGITUDE")
    for label, value in (("window_start", window_start),
                         ("window_end", window_end), ("now", now)):
        if value is not None and (value.tzinfo is None
                                  or value.utcoffset() is None):
            raise NWSWeatherSourceError(f"NAIVE_DATETIME:{label}")
    if window_end <= window_start:
        raise NWSWeatherSourceError("INVALID_WINDOW")
    retrieved_at = now or datetime.now(timezone.utc)

    points = _open_json(points_url(latitude, longitude), opener=opener)
    props = points.get("properties")
    if not isinstance(props, Mapping):
        raise NWSWeatherSourceError("POINTS_RESPONSE_INCOMPLETE")
    stations_url = props.get("observationStations")
    hourly_url = props.get("forecastHourly")
    if not isinstance(stations_url, str) or not isinstance(hourly_url, str):
        raise NWSWeatherSourceError("POINTS_RESPONSE_INCOMPLETE")

    stations_payload = _open_json(stations_url, opener=opener)
    station_features = stations_payload.get("features")
    if not isinstance(station_features, list) or not station_features:
        raise NWSWeatherSourceError("STATIONS_RESPONSE_EMPTY")

    # Every tried station is evaluated; the observation closest to the
    # window start wins (station order breaks ties). A nearer station's
    # old report must not shadow a fresher report from the next station.
    observation: dict[str, Any] | None = None
    best_key: tuple[timedelta, int] | None = None
    saw_stale = False
    stations_tried: list[str] = []
    station_errors: list[str] = []
    for order, feature in enumerate(station_features[:MAX_STATIONS_TRIED]):
        sprops = feature.get("properties") if isinstance(feature, Mapping) else None
        if not isinstance(sprops, Mapping):
            continue
        station_id = sprops.get("stationIdentifier")
        if not isinstance(station_id, str) or not station_id:
            continue
        stations_tried.append(station_id)
        try:
            obs_features = _fetch_station_observations(
                station_id, window_start=window_start,
                window_end=window_end, opener=opener)
        except NWSWeatherSourceError as exc:
            station_errors.append(f"{station_id}:{exc}")
            continue
        candidate, candidate_reason = select_window_observation(
            obs_features, station_id=station_id,
            station_name=sprops.get("name"),
            window_start=window_start, window_end=window_end,
            now=retrieved_at)
        if candidate_reason == REASON_STALE:
            saw_stale = True
        if candidate is None:
            continue
        observed_at = _parse_instant(candidate["observed_at"])
        if observed_at is None:
            continue
        key = (abs(observed_at - window_start), order)
        if best_key is None or key < best_key:
            best_key, observation = key, candidate
    reason = None if observation is not None else (
        REASON_STALE if saw_stale else REASON_NO_OBSERVATION)

    forecast_periods: list[dict[str, Any]] = []
    forecast_error: str | None = None
    try:
        hourly = _open_json(hourly_url, opener=opener)
        forecast_periods = normalize_forecast_periods(
            hourly, window_start=window_start, window_end=window_end)
    except NWSWeatherSourceError as exc:
        forecast_error = str(exc)

    return {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE,
        "research_only": True,
        "validation_status": "PENDING_VALIDATION",
        "pricing_impact": "NONE",
        "staking_allowed": False,
        "latitude": float(latitude),
        "longitude": float(longitude),
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "retrieved_at": retrieved_at.isoformat(),
        "status": STATUS_VERIFIED if observation is not None
                  else STATUS_UNVERIFIED,
        "status_reason": None if observation is not None else reason,
        "observation": observation,
        "forecast_periods": forecast_periods,
        "provenance": {
            "points_url": points_url(latitude, longitude),
            "forecast_office": props.get("cwa"),
            "grid_id": props.get("gridId"),
            "grid_x": props.get("gridX"),
            "grid_y": props.get("gridY"),
            "stations_url": stations_url,
            "hourly_forecast_url": hourly_url,
            "stations_tried": stations_tried,
            "station_errors": station_errors,
            "forecast_error": forecast_error,
        },
    }
