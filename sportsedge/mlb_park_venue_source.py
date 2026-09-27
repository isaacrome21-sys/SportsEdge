"""MLB park/venue context from public StatsAPI.

This lane binds a game to its physical venue and static field metadata. It is
context/acquisition only and never creates Model_P.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Callable, Mapping
from urllib.request import Request, urlopen

from .source_lineage import canonical_json_sha256

MLB_STATSAPI = "https://statsapi.mlb.com/api/v1"
SOURCE = "MLB_STATSAPI_PARK_VENUE"
SCHEMA_VERSION = "mlb_park_venue_source_v1"


class MLBParkVenueSourceError(RuntimeError):
    pass


def venue_url(venue_id: int) -> str:
    return f"{MLB_STATSAPI}/venues/{int(venue_id)}?hydrate=location,fieldInfo,timezone"


def _open_json(url: str, *, opener: Callable = urlopen) -> dict[str, Any]:
    req = Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "SportsEdge-MLB-ParkVenue/1.0",
    })
    try:
        with opener(req, timeout=30) as response:
            raw = response.read()
    except Exception as exc:
        raise MLBParkVenueSourceError(f"VENUE_FETCH_FAILED:{url}") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise MLBParkVenueSourceError("VENUE_RESPONSE_NOT_JSON") from exc
    if not isinstance(payload, dict):
        raise MLBParkVenueSourceError("VENUE_RESPONSE_NOT_OBJECT")
    return payload


def _venue_id(live_payload: Mapping[str, Any] | None) -> int | None:
    game_data = (live_payload or {}).get("gameData") or {}
    venue = game_data.get("venue") if isinstance(game_data, Mapping) else {}
    try:
        return int((venue or {}).get("id")) if isinstance(venue, Mapping) else None
    except (TypeError, ValueError):
        return None


def _first_venue(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    venues = payload.get("venues")
    if isinstance(venues, list):
        for row in venues:
            if isinstance(row, Mapping):
                return row
    if payload.get("id") is not None:
        return payload
    return None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_venue(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    venue = _first_venue(payload)
    if venue is None:
        return None
    location = venue.get("location") or {}
    field = venue.get("fieldInfo") or {}
    timezone_block = venue.get("timeZone") or venue.get("timezone") or {}
    if not isinstance(location, Mapping):
        location = {}
    if not isinstance(field, Mapping):
        field = {}
    if not isinstance(timezone_block, Mapping):
        timezone_block = {}

    coords = location.get("defaultCoordinates") or {}
    if not isinstance(coords, Mapping):
        coords = {}
    latitude = _float(location.get("latitude"))
    longitude = _float(location.get("longitude"))
    if latitude is None:
        latitude = _float(coords.get("latitude"))
    if longitude is None:
        longitude = _float(coords.get("longitude"))

    azimuth = _float(location.get("azimuthAngle"))
    if azimuth is not None:
        azimuth %= 360.0
    elevation = _float(location.get("elevation"))

    dimensions: dict[str, float | None] = {}
    for key in ("leftLine", "leftCenter", "center", "rightCenter", "rightLine"):
        dimensions[key] = _float(field.get(key))

    try:
        venue_id = int(venue.get("id"))
    except (TypeError, ValueError):
        venue_id = None
    return {
        "venue_id": venue_id,
        "venue_name": str(venue.get("name") or "").strip() or None,
        "city": str(location.get("city") or "").strip() or None,
        "state": str(location.get("stateAbbrev") or location.get("state") or "").strip() or None,
        "country": str(location.get("country") or "").strip() or None,
        "latitude": latitude,
        "longitude": longitude,
        "timezone_id": str(timezone_block.get("id") or timezone_block.get("tz") or "").strip() or None,
        "azimuth_angle_degrees": azimuth,
        "azimuth_source_field": "location.azimuthAngle" if azimuth is not None else None,
        "elevation_raw": elevation,
        "roof_type": str(field.get("roofType") or "").strip() or None,
        "turf_type": str(field.get("turfType") or "").strip() or None,
        "capacity": int(field["capacity"]) if str(field.get("capacity") or "").isdigit() else None,
        "field_dimensions_ft": dimensions,
    }


def acquire_park_venue_context(
    *,
    game_pk: int,
    as_of: datetime,
    live_payload: Mapping[str, Any] | None = None,
    opener: Callable = urlopen,
    venue_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    venue_id = _venue_id(live_payload)
    errors: list[str] = []
    raw: Mapping[str, Any] | None = venue_payload
    source_url: str | None = None

    if raw is None and venue_id is not None:
        source_url = venue_url(venue_id)
        try:
            raw = _open_json(source_url, opener=opener)
        except MLBParkVenueSourceError as exc:
            errors.append(str(exc))

    parsed = parse_venue(raw or {}) if raw is not None else None
    if parsed is not None and parsed.get("venue_id") is None and venue_id is not None:
        parsed["venue_id"] = venue_id

    if venue_id is None and parsed is None:
        status = "MISSING_VENUE_ID"
    elif parsed is None:
        status = "UNAVAILABLE"
    else:
        status = "AVAILABLE"

    payload = {
        "schema_version": SCHEMA_VERSION,
        "game_pk": int(game_pk),
        "as_of_utc": as_of.astimezone(timezone.utc).isoformat(),
        "source": SOURCE,
        "source_url": source_url,
        "venue": parsed,
        "errors": errors,
        "status": status,
        "model_p_eligible": False,
    }
    payload["payload_sha256"] = canonical_json_sha256(payload)
    return payload
