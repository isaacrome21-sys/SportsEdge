"""Reconstructed historical CFB weather for candidate selection only.

This module reconstructs the frozen weather feature values from CFBD venue metadata
and Open-Meteo ERA5 historical reanalysis. It deliberately creates no historical
PIT or promotion authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping, Sequence
from urllib.parse import urlencode

UTC = timezone.utc
WEATHER_CONTRACT = "CFBD_VENUES_OPEN_METEO_ERA5_RECONSTRUCTED_CURRENT_PROVIDER_VINTAGE"
OPEN_METEO_ARCHIVE_ROOT = "https://archive-api.open-meteo.com/v1/archive"


class CFBReconstructedWeatherError(ValueError):
    pass


@dataclass(frozen=True)
class VenueSpec:
    venue_id: int
    name: str
    latitude: float
    longitude: float
    dome: bool


def _num(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise CFBReconstructedWeatherError(f"CFB_RECONSTRUCTED_WEATHER_NUMBER_INVALID:{name}")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise CFBReconstructedWeatherError(
            f"CFB_RECONSTRUCTED_WEATHER_NUMBER_INVALID:{name}"
        ) from exc
    if not isfinite(out):
        raise CFBReconstructedWeatherError(f"CFB_RECONSTRUCTED_WEATHER_NUMBER_INVALID:{name}")
    return out


def parse_venues(rows: Sequence[Mapping[str, Any]]) -> dict[int, VenueSpec]:
    out: dict[int, VenueSpec] = {}
    for raw in rows:
        vid_raw = raw.get("id")
        if vid_raw is None:
            continue
        try:
            vid = int(vid_raw)
        except (TypeError, ValueError) as exc:
            raise CFBReconstructedWeatherError("CFB_RECONSTRUCTED_VENUE_ID_INVALID") from exc
        if vid in out:
            raise CFBReconstructedWeatherError(f"CFB_RECONSTRUCTED_VENUE_DUPLICATE:{vid}")
        lat = _num(raw.get("latitude"), f"venue.{vid}.latitude")
        lon = _num(raw.get("longitude"), f"venue.{vid}.longitude")
        if not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise CFBReconstructedWeatherError(
                f"CFB_RECONSTRUCTED_VENUE_COORDINATES_INVALID:{vid}"
            )
        dome_raw = raw.get("dome")
        if dome_raw is None:
            dome = False
        elif type(dome_raw) is bool:
            dome = dome_raw
        else:
            raise CFBReconstructedWeatherError(f"CFB_RECONSTRUCTED_VENUE_DOME_INVALID:{vid}")
        out[vid] = VenueSpec(
            venue_id=vid,
            name=str(raw.get("name") or "").strip(),
            latitude=lat,
            longitude=lon,
            dome=dome,
        )
    if not out:
        raise CFBReconstructedWeatherError("CFB_RECONSTRUCTED_VENUES_EMPTY")
    return out


def archive_url(venues: Sequence[VenueSpec], start_date: str, end_date: str) -> str:
    if not venues:
        raise CFBReconstructedWeatherError("CFB_RECONSTRUCTED_WEATHER_BATCH_EMPTY")
    params = {
        "latitude": ",".join(f"{venue.latitude:.6f}" for venue in venues),
        "longitude": ",".join(f"{venue.longitude:.6f}" for venue in venues),
        "start_date": start_date,
        "end_date": end_date,
        "hourly": "temperature_2m,wind_speed_10m",
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "timezone": "GMT",
        "models": "era5",
    }
    return OPEN_METEO_ARCHIVE_ROOT + "?" + urlencode(params)


def _locations(payload: object, expected: int) -> list[Mapping[str, Any]]:
    if expected == 1 and isinstance(payload, Mapping):
        rows = [payload]
    elif isinstance(payload, list):
        rows = [row for row in payload if isinstance(row, Mapping)]
    else:
        raise CFBReconstructedWeatherError("CFB_RECONSTRUCTED_WEATHER_ARCHIVE_SHAPE_INVALID")
    if len(rows) != expected:
        raise CFBReconstructedWeatherError(
            f"CFB_RECONSTRUCTED_WEATHER_ARCHIVE_LOCATION_COUNT:{len(rows)}:{expected}"
        )
    return rows


def parse_archive_batch(
    payload: object,
    venues: Sequence[VenueSpec],
) -> dict[int, dict[str, tuple[float, float]]]:
    rows = _locations(payload, len(venues))
    out: dict[int, dict[str, tuple[float, float]]] = {}
    for venue, raw in zip(venues, rows):
        if raw.get("utc_offset_seconds") not in (0, 0.0):
            raise CFBReconstructedWeatherError(
                f"CFB_RECONSTRUCTED_WEATHER_ARCHIVE_NOT_UTC:{venue.venue_id}"
            )
        units = raw.get("hourly_units")
        hourly = raw.get("hourly")
        if not isinstance(units, Mapping) or not isinstance(hourly, Mapping):
            raise CFBReconstructedWeatherError(
                f"CFB_RECONSTRUCTED_WEATHER_ARCHIVE_HOURLY_MISSING:{venue.venue_id}"
            )
        if units.get("temperature_2m") not in {"°F", "°Fahrenheit", "F"}:
            raise CFBReconstructedWeatherError(
                f"CFB_RECONSTRUCTED_WEATHER_ARCHIVE_TEMP_UNIT:{venue.venue_id}:{units.get('temperature_2m')}"
            )
        if units.get("wind_speed_10m") not in {"mp/h", "mph"}:
            raise CFBReconstructedWeatherError(
                f"CFB_RECONSTRUCTED_WEATHER_ARCHIVE_WIND_UNIT:{venue.venue_id}:{units.get('wind_speed_10m')}"
            )
        times = hourly.get("time")
        temps = hourly.get("temperature_2m")
        winds = hourly.get("wind_speed_10m")
        if not isinstance(times, list) or not isinstance(temps, list) or not isinstance(winds, list):
            raise CFBReconstructedWeatherError(
                f"CFB_RECONSTRUCTED_WEATHER_ARCHIVE_COLUMNS_INVALID:{venue.venue_id}"
            )
        if not (len(times) == len(temps) == len(winds)) or len(set(map(str, times))) != len(times):
            raise CFBReconstructedWeatherError(
                f"CFB_RECONSTRUCTED_WEATHER_ARCHIVE_GRID_INVALID:{venue.venue_id}"
            )
        grid: dict[str, tuple[float, float]] = {}
        for stamp, temp, wind in zip(times, temps, winds):
            key = str(stamp)
            t = _num(temp, f"archive.{venue.venue_id}.temperature")
            w = _num(wind, f"archive.{venue.venue_id}.wind")
            if w < 0:
                raise CFBReconstructedWeatherError(
                    f"CFB_RECONSTRUCTED_WEATHER_ARCHIVE_WIND_NEGATIVE:{venue.venue_id}"
                )
            grid[key] = (t, w)
        out[venue.venue_id] = grid
    return out


def kickoff_hour_key(start_ts: object) -> str:
    text = str(start_ts or "").strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CFBReconstructedWeatherError("CFB_RECONSTRUCTED_WEATHER_KICKOFF_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CFBReconstructedWeatherError("CFB_RECONSTRUCTED_WEATHER_KICKOFF_INVALID")
    hour = parsed.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    return hour.strftime("%Y-%m-%dT%H:00")


def weather_row(
    *,
    game: Mapping[str, Any],
    venue: VenueSpec,
    archive_grid: Mapping[str, tuple[float, float]] | None,
    retrieved_at_utc: str,
) -> dict[str, Any]:
    if venue.dome:
        temp, wind = 70.0, 0.0
    else:
        if archive_grid is None:
            raise CFBReconstructedWeatherError(
                f"CFB_RECONSTRUCTED_WEATHER_GRID_MISSING:{game.get('id')}"
            )
        key = kickoff_hour_key(game.get("startDate"))
        pair = archive_grid.get(key)
        if pair is None:
            raise CFBReconstructedWeatherError(
                f"CFB_RECONSTRUCTED_WEATHER_KICKOFF_HOUR_MISSING:{game.get('id')}:{key}"
            )
        temp, wind = pair
    return {
        "source": WEATHER_CONTRACT,
        "retrieved_at_utc": retrieved_at_utc,
        "provenance_class": "RECONSTRUCTED_HISTORICAL_NOT_PIT",
        "archive_model": "ERA5" if not venue.dome else None,
        "venue_id": venue.venue_id,
        "venue_name": venue.name,
        "gameIndoors": venue.dome,
        "windSpeed": float(wind),
        "temperature": float(temp),
    }


__all__ = [
    "CFBReconstructedWeatherError",
    "VenueSpec",
    "WEATHER_CONTRACT",
    "OPEN_METEO_ARCHIVE_ROOT",
    "archive_url",
    "kickoff_hour_key",
    "parse_archive_batch",
    "parse_venues",
    "weather_row",
]
