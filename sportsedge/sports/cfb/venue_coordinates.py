from __future__ import annotations

from math import isfinite
from typing import Any, Mapping, Sequence


def extract_coordinate_pair(raw: Mapping[str, Any]) -> tuple[object, object]:
    location = raw.get("location") if isinstance(raw.get("location"), Mapping) else {}
    candidates = (
        (raw.get("latitude"), raw.get("longitude")),
        (raw.get("lat"), raw.get("lng")),
        (raw.get("lat"), raw.get("lon")),
        (location.get("latitude"), location.get("longitude")),
        (location.get("lat"), location.get("lng")),
        (location.get("lat"), location.get("lon")),
        (location.get("y"), location.get("x")),
    )
    for lat, lon in candidates:
        if lat is not None and lon is not None:
            return lat, lon
    return None, None


def try_venue_coordinates(raw: Mapping[str, Any]) -> tuple[float, float] | None:
    lat, lon = extract_coordinate_pair(raw)
    try:
        lat_f, lon_f = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if not isfinite(lat_f) or not isfinite(lon_f) or not (-90 <= lat_f <= 90) or not (-180 <= lon_f <= 180):
        return None
    return lat_f, lon_f


def venue_indexes(rows: Sequence[Mapping[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}
    for raw in rows:
        venue_id = str(raw.get("id") or "").strip()
        name = str(raw.get("name") or "").strip()
        dome = raw.get("dome")
        if not venue_id or not name or type(dome) is not bool:
            continue
        parsed = try_venue_coordinates(raw)
        if parsed is None:
            continue
        lat, lon = parsed
        normalized = {
            "venue_id": venue_id,
            "name": name,
            "dome": dome,
            "latitude": lat,
            "longitude": lon,
        }
        by_id[venue_id] = normalized
        by_name[name.casefold()] = normalized
    return by_id, by_name
