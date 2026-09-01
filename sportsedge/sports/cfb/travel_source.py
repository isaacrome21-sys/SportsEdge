from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from math import atan2, cos, radians, sin, sqrt
from typing import Any, Callable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .context_autopull import CFBContextError
from .source import CFBD_BASE


def _haversine_km(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    radius = 6371.0088
    lat1, lon1, lat2, lon2 = map(radians, (float(a_lat), float(a_lon), float(b_lat), float(b_lon)))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = sin(dlat / 2.0) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2.0) ** 2
    return radius * 2.0 * atan2(sqrt(h), sqrt(max(0.0, 1.0 - h)))


def fetch_cfbd_fbs_venue_registry(
    *, season: int, cfbd_api_key: str, opener: Callable = urlopen,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], str, str]:
    """Fetch FBS home-venue metadata with exact-byte provenance.

    Returns indexes by canonical school name and venue id. CFBD /teams/fbs embeds
    the authoritative team home-location object including coordinates, timezone,
    elevation, dome/grass and venue id. This does not guess neutral-site venues.
    """
    key = str(cfbd_api_key or "").strip()
    if not key:
        raise CFBContextError("CFBD_API_KEY_REQUIRED")
    query = urlencode({"year": int(season)})
    uri = f"{CFBD_BASE}/teams/fbs?{query}"
    req = Request(uri, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    try:
        with opener(req, timeout=20) as response:
            raw = response.read()
    except Exception as exc:
        raise CFBContextError("CFBD FBS venue registry fetch failed") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise CFBContextError("CFBD FBS venue registry JSON invalid") from exc
    if not isinstance(payload, list):
        raise CFBContextError("CFBD FBS venue registry not list")

    by_team: dict[str, dict[str, Any]] = {}
    by_venue: dict[str, dict[str, Any]] = {}
    for row in payload:
        if not isinstance(row, Mapping):
            continue
        school = str(row.get("school") or "").strip()
        location = row.get("location")
        if not school or not isinstance(location, Mapping):
            continue
        lat, lon = location.get("latitude"), location.get("longitude")
        if lat is None or lon is None:
            continue
        try:
            lat_f, lon_f = float(lat), float(lon)
        except (TypeError, ValueError):
            continue
        if not (-90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0):
            continue
        venue_id = location.get("id")
        record = {
            "school": school,
            "venue_id": None if venue_id in (None, "") else str(venue_id),
            "venue_name": str(location.get("name") or "").strip() or None,
            "latitude": lat_f,
            "longitude": lon_f,
            "timezone": str(location.get("timezone") or "").strip() or None,
            "elevation_ft": None if location.get("elevation") in (None, "") else float(location.get("elevation")),
            "dome": None if location.get("dome") is None else bool(location.get("dome")),
            "grass": None if location.get("grass") is None else bool(location.get("grass")),
        }
        by_team[school] = record
        if record["venue_id"] is not None:
            by_venue[str(record["venue_id"])] = record
    if not by_team:
        raise CFBContextError("CFBD FBS venue registry empty")
    return by_team, by_venue, sha256(raw).hexdigest(), uri


def resolve_game_venue(
    *, home_team: str, venue_id: Any, neutral_site: bool,
    by_team: Mapping[str, Mapping[str, Any]], by_venue: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    if venue_id not in (None, ""):
        exact = by_venue.get(str(venue_id))
        if exact is not None:
            return exact
    if neutral_site:
        return None
    return by_team.get(str(home_team))


def _timezone_offset_hours(tz_name: str | None, instant: datetime) -> float | None:
    if not tz_name:
        return None
    try:
        zone = ZoneInfo(str(tz_name))
    except ZoneInfoNotFoundError:
        return None
    offset = instant.astimezone(zone).utcoffset()
    return None if offset is None else offset.total_seconds() / 3600.0


def enrich_rest_travel_payload(
    *, payload: Mapping[str, Any], current_game: Mapping[str, Any], previous_game: Mapping[str, Any],
    current_kickoff: datetime, by_team: Mapping[str, Mapping[str, Any]],
    by_venue: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Add coordinate-derived travel, timezone shift and destination elevation.

    Exact venue-id matches win. A non-neutral game's home-team venue is the only
    fallback. Neutral venues with no exact venue-id record remain unavailable.
    """
    out = dict(payload)
    previous_venue = resolve_game_venue(
        home_team=str(previous_game.get("home") or ""),
        venue_id=previous_game.get("venue_id"),
        neutral_site=bool(previous_game.get("neutral", False)),
        by_team=by_team, by_venue=by_venue,
    )
    current_venue = resolve_game_venue(
        home_team=str(current_game.get("home_team") or ""),
        venue_id=current_game.get("venue_id"),
        neutral_site=bool(current_game.get("neutral_site", False)),
        by_team=by_team, by_venue=by_venue,
    )
    out["destination_elevation_ft"] = None if current_venue is None else current_venue.get("elevation_ft")
    out["destination_timezone"] = None if current_venue is None else current_venue.get("timezone")
    out["previous_timezone"] = None if previous_venue is None else previous_venue.get("timezone")
    if previous_venue is None or current_venue is None:
        out["travel_distance_km"] = None
        out["timezone_shift_hours"] = None
        out["travel_status"] = "UNAVAILABLE_UNRESOLVED_VENUE"
        return out
    out["travel_distance_km"] = round(_haversine_km(
        float(previous_venue["latitude"]), float(previous_venue["longitude"]),
        float(current_venue["latitude"]), float(current_venue["longitude"]),
    ), 3)
    prev_offset = _timezone_offset_hours(previous_venue.get("timezone"), current_kickoff)
    cur_offset = _timezone_offset_hours(current_venue.get("timezone"), current_kickoff)
    out["timezone_shift_hours"] = None if prev_offset is None or cur_offset is None else round(cur_offset - prev_offset, 3)
    out["travel_status"] = "AVAILABLE" if out["timezone_shift_hours"] is not None else "PARTIAL_TIMEZONE_UNAVAILABLE"
    out["previous_venue_resolved_id"] = previous_venue.get("venue_id")
    out["current_venue_resolved_id"] = current_venue.get("venue_id")
    return out
