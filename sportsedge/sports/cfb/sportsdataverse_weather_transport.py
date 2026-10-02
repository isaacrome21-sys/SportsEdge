"""Frozen public historical-weather transport for the CFB SportsDataverse lane.

Venue identity is bound to a pinned public stadium snapshot. Outdoor weather is
read from Open-Meteo Archive in venue-season windows and sampled at the nearest
kickoff hour without interpolation. Missing venues, coordinates, hours, or values
fail closed. No sportsbook or CFBD API credential is required.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone, timedelta
from hashlib import sha256
import io
from math import isfinite
from typing import Any, Mapping

class SDVWeatherTransportError(ValueError):
    pass

SOURCE_ID = "OPEN_METEO_ARCHIVE_V1"
BASE_URL = "https://archive-api.open-meteo.com/v1/archive"
HOURLY = ("temperature_2m", "wind_speed_10m")

VENUE_SOURCE_REPOSITORY = "mslade50/football_weather"
VENUE_SOURCE_COMMIT = "aea8274b8c2035372d19d8a509423b0645b7bfe9"
VENUE_SOURCE_PATH = "data/stadiums.csv"
VENUE_SOURCE_GIT_BLOB_SHA1 = "cd1babd57d6457c502dd116036058d03e2968d32"
VENUE_SOURCE_SHA256 = "aa9599316d015eb10bf019c2fae937c09140061f9940b29dde884030183820f2"
VENUE_SOURCE_URL = (
    "https://raw.githubusercontent.com/"
    f"{VENUE_SOURCE_REPOSITORY}/{VENUE_SOURCE_COMMIT}/{VENUE_SOURCE_PATH}"
)


def _number(value: Any, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise SDVWeatherTransportError(f"CFB_SDV_WEATHER_FIELD_INVALID:{field}") from exc
    if not isfinite(out):
        raise SDVWeatherTransportError(f"CFB_SDV_WEATHER_FIELD_INVALID:{field}")
    return out


def _venue_name(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def venue_indexes(raw: bytes) -> tuple[dict[int, dict[str, Any]], dict[str, dict[str, Any]]]:
    if sha256(raw).hexdigest() != VENUE_SOURCE_SHA256:
        raise SDVWeatherTransportError("CFB_SDV_VENUE_SOURCE_HASH_MISMATCH")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SDVWeatherTransportError("CFB_SDV_VENUE_SOURCE_UTF8_REQUIRED") from exc
    reader = csv.DictReader(io.StringIO(text))
    fields = set(reader.fieldnames or ())
    required = {"stadium_id", "name", "aliases", "cfbd_venue_id", "lat", "lon", "roof_type"}
    missing = sorted(required - fields)
    if missing:
        raise SDVWeatherTransportError(
            "CFB_SDV_VENUE_SOURCE_COLUMNS_MISSING:" + ",".join(missing)
        )
    by_id: dict[int, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}
    ambiguous_names: set[str] = set()
    row_count = 0
    for row in reader:
        row_count += 1
        stadium_id = str(row.get("stadium_id") or "").strip()
        name = str(row.get("name") or "").strip()
        if not stadium_id or not name:
            raise SDVWeatherTransportError("CFB_SDV_VENUE_IDENTITY_REQUIRED")
        lat = _number(row.get("lat"), f"venue.{stadium_id}.lat")
        lon = _number(row.get("lon"), f"venue.{stadium_id}.lon")
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            raise SDVWeatherTransportError(
                f"CFB_SDV_VENUE_COORDINATES_INVALID:{stadium_id}"
            )
        roof = str(row.get("roof_type") or "").strip().lower()
        if roof not in {"open", "dome", "retractable"}:
            raise SDVWeatherTransportError(
                f"CFB_SDV_VENUE_ROOF_TYPE_INVALID:{stadium_id}:{roof}"
            )
        raw_id = str(row.get("cfbd_venue_id") or "").strip()
        cfbd_id = None
        if raw_id:
            try:
                cfbd_id = int(float(raw_id))
            except ValueError as exc:
                raise SDVWeatherTransportError("CFB_SDV_VENUE_ID_INVALID") from exc
        normalized = {
            "stadium_id": stadium_id,
            "venue_id": cfbd_id,
            "name": name,
            "latitude": lat,
            "longitude": lon,
            "game_indoor": roof in {"dome", "retractable"},
            "roof_type": roof,
        }
        if cfbd_id is not None:
            prior = by_id.get(cfbd_id)
            if prior is not None and prior != normalized:
                raise SDVWeatherTransportError(
                    f"CFB_SDV_VENUE_DUPLICATE_CONFLICT:{cfbd_id}"
                )
            by_id[cfbd_id] = normalized

        names = [name]
        names.extend(
            token.strip()
            for token in str(row.get("aliases") or "").split("|")
            if token.strip()
        )
        for candidate in names:
            key = _venue_name(candidate)
            if not key:
                continue
            prior = by_name.get(key)
            if prior is None:
                by_name[key] = normalized
            elif prior["stadium_id"] != stadium_id:
                ambiguous_names.add(key)
    for key in ambiguous_names:
        by_name.pop(key, None)
    if row_count == 0 or not by_name:
        raise SDVWeatherTransportError("CFB_SDV_VENUE_SOURCE_EMPTY")
    return by_id, by_name


def venue_index(raw: bytes) -> dict[int, dict[str, Any]]:
    return venue_indexes(raw)[0]


def resolve_venue(
    *,
    by_id: Mapping[int, Mapping[str, Any]],
    by_name: Mapping[str, Mapping[str, Any]],
    venue_id: int,
    venue_name: str,
) -> tuple[dict[str, Any], str]:
    found = by_id.get(int(venue_id))
    if found is not None:
        return dict(found), "CFBD_VENUE_ID"
    key = _venue_name(venue_name)
    found = by_name.get(key)
    if found is None:
        raise SDVWeatherTransportError(
            f"CFB_SDV_HISTORICAL_VENUE_UNRESOLVED:{venue_id}:{venue_name}"
        )
    return dict(found), "PINNED_EXACT_NAME_OR_ALIAS"

def request_params(
    *,
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    try:
        start = datetime.fromisoformat(str(start_date)).date()
        end = datetime.fromisoformat(str(end_date)).date()
    except ValueError as exc:
        raise SDVWeatherTransportError("CFB_SDV_WEATHER_WINDOW_DATE_INVALID") from exc
    if end < start:
        raise SDVWeatherTransportError("CFB_SDV_WEATHER_WINDOW_ORDER_INVALID")
    return {
        "latitude": float(latitude),
        "longitude": float(longitude),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "hourly": ",".join(HOURLY),
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "timezone": "UTC",
    }


def kickoff_date(value: str) -> str:
    return _utc(value).date().isoformat()


def select_kickoff_hour(
    payload: Mapping[str, Any],
    *,
    game_id: int,
    kickoff_utc: str,
    game_indoor: bool,
) -> dict[str, Any]:
    if type(game_indoor) is not bool:
        raise SDVWeatherTransportError("CFB_SDV_WEATHER_INDOOR_FLAG_REQUIRED")
    if game_indoor:
        return {
            "game_id": int(game_id),
            "game_indoor": True,
            "wind_speed": None,
            "temperature": None,
        }
    hourly = payload.get("hourly")
    if not isinstance(hourly, Mapping):
        raise SDVWeatherTransportError("CFB_SDV_WEATHER_HOURLY_REQUIRED")
    times = list(hourly.get("time") or [])
    temps = list(hourly.get("temperature_2m") or [])
    winds = list(hourly.get("wind_speed_10m") or [])
    if not (len(times) == len(temps) == len(winds)):
        raise SDVWeatherTransportError("CFB_SDV_WEATHER_HOURLY_LENGTH_MISMATCH")
    target = _utc(kickoff_utc)
    if target.minute >= 30:
        target = target.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        target = target.replace(minute=0, second=0, microsecond=0)
    key = target.strftime("%Y-%m-%dT%H:%M")
    if key not in times:
        raise SDVWeatherTransportError(
            f"CFB_SDV_WEATHER_KICKOFF_HOUR_MISSING:{game_id}"
        )
    i = times.index(key)
    if temps[i] is None or winds[i] is None:
        raise SDVWeatherTransportError(
            f"CFB_SDV_WEATHER_KICKOFF_VALUES_MISSING:{game_id}"
        )
    return {
        "game_id": int(game_id),
        "game_indoor": False,
        "wind_speed": _number(winds[i], f"weather.{game_id}.wind_speed"),
        "temperature": _number(temps[i], f"weather.{game_id}.temperature"),
    }


def _utc(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise SDVWeatherTransportError("CFB_SDV_WEATHER_KICKOFF_INVALID") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise SDVWeatherTransportError("CFB_SDV_WEATHER_KICKOFF_TZ_REQUIRED")
    return dt.astimezone(timezone.utc)


__all__ = [
    "BASE_URL",
    "HOURLY",
    "SOURCE_ID",
    "SDVWeatherTransportError",
    "VENUE_SOURCE_COMMIT",
    "VENUE_SOURCE_GIT_BLOB_SHA1",
    "VENUE_SOURCE_PATH",
    "VENUE_SOURCE_REPOSITORY",
    "VENUE_SOURCE_SHA256",
    "VENUE_SOURCE_URL",
    "kickoff_date",
    "request_params",
    "resolve_venue",
    "select_kickoff_hour",
    "venue_index",
    "venue_indexes",
]
