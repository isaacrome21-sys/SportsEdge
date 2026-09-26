"""CFB reconstructed acquire weather helpers (null-weather path).

Unresolved venues keep game rows with temp/wind null and source WEATHER_MISSING.
Those games are excluded from Open-Meteo batches only. No Model_P / Truth Gate /
promotion / eligibility / OFFICIAL authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.request import urlopen

from sportsedge.sports.cfb.venue_coordinates import venue_indexes

WEATHER_CONTRACT = "CFBD_VENUES_OPEN_METEO_ERA5_RECONSTRUCTED_CURRENT_PROVIDER_VINTAGE"


class CFBAcquisitionError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dt(value: object, code: str) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        raise CFBAcquisitionError(code)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CFBAcquisitionError(code) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CFBAcquisitionError(code)
    return parsed.astimezone(timezone.utc)


def resolve_venue(
    game: Mapping[str, Any],
    *,
    by_id: Mapping[str, Mapping[str, Any]],
    by_name: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any] | None:
    venue_id = str(game.get("venueId") or game.get("venue_id") or "").strip()
    if venue_id and venue_id in by_id:
        return dict(by_id[venue_id])
    venue_name = str(game.get("venue") or "").strip()
    if venue_name and venue_name.casefold() in by_name:
        return dict(by_name[venue_name.casefold()])
    return None


def _venue_indexes(rows: Sequence[Mapping[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_id, by_name = venue_indexes(rows)
    if not by_id:
        raise CFBAcquisitionError("CFB_VENUES_EMPTY")
    return by_id, by_name


def _normalize_open_meteo_payload(payload: Any, expected: int) -> list[Mapping[str, Any]]:
    if expected == 1 and isinstance(payload, Mapping):
        rows = [payload]
    elif isinstance(payload, list):
        rows = payload
    else:
        raise CFBAcquisitionError("CFB_OPEN_METEO_PAYLOAD_INVALID")
    if len(rows) != expected or not all(isinstance(row, Mapping) for row in rows):
        raise CFBAcquisitionError(f"CFB_OPEN_METEO_LOCATION_COUNT_MISMATCH:{len(rows)}:{expected}")
    return [dict(row) for row in rows]


def _hourly_index(payload: Mapping[str, Any]) -> dict[str, tuple[float, float]]:
    hourly = payload.get("hourly")
    if not isinstance(hourly, Mapping):
        raise CFBAcquisitionError("CFB_OPEN_METEO_HOURLY_MISSING")
    times = hourly.get("time")
    temps = hourly.get("temperature_2m")
    winds = hourly.get("wind_speed_10m")
    if not isinstance(times, list) or not isinstance(temps, list) or not isinstance(winds, list):
        raise CFBAcquisitionError("CFB_OPEN_METEO_HOURLY_ARRAY_INVALID")
    if len(times) != len(temps) or len(times) != len(winds):
        raise CFBAcquisitionError("CFB_OPEN_METEO_HOURLY_LENGTH_MISMATCH")
    out: dict[str, tuple[float, float]] = {}
    for stamp, temp, wind in zip(times, temps, winds):
        if temp is None or wind is None:
            continue
        try:
            temp_f, wind_mph = float(temp), float(wind)
        except (TypeError, ValueError):
            continue
        if isfinite(temp_f) and isfinite(wind_mph):
            out[str(stamp)] = (temp_f, wind_mph)
    if not out:
        raise CFBAcquisitionError("CFB_OPEN_METEO_HOURLY_EMPTY")
    return out


def weather_hour_key(start_ts: object) -> str:
    kickoff = _dt(start_ts, "CFB_GAME_KICKOFF_INVALID")
    floored = kickoff.replace(minute=0, second=0, microsecond=0)
    return floored.strftime("%Y-%m-%dT%H:00")


def build_weather_with_null_path(
    *,
    games: Sequence[Mapping[str, Any]],
    venues_raw: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
    weather_cache_root: Path,
    weather_request_fn: Callable,
    fetch_public_weather_fn: Callable,
    opener: Callable = urlopen,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], int, int]:
    """Keep all game rows. Unresolved venues get WEATHER_MISSING; not sent to Open-Meteo."""
    by_id, by_name = _venue_indexes(venues_raw)
    resolved: dict[str, dict[str, Any]] = {}
    weather_missing: list[str] = []
    for game in games:
        gid = str(game["game_id"])
        venue = resolve_venue(game, by_id=by_id, by_name=by_name)
        if venue is None:
            weather_missing.append(gid)
            continue
        resolved[gid] = venue

    weather_by_game: dict[str, dict[str, Any]] = {}
    outdoor_by_season: dict[int, list[Mapping[str, Any]]] = {}
    venue_retrieved = _now()
    for gid in weather_missing:
        weather_by_game[gid] = {
            "gameIndoors": None,
            "windSpeed": None,
            "temperature": None,
            "source": "WEATHER_MISSING",
            "retrieved_at_utc": venue_retrieved,
            "venue_id": None,
            "weather_status": "WEATHER_MISSING",
        }
    for game in games:
        gid = str(game["game_id"])
        venue = resolved.get(gid)
        if venue is None:
            continue
        if venue["dome"]:
            weather_by_game[gid] = {
                "gameIndoors": True,
                "windSpeed": 0.0,
                "temperature": 70.0,
                "source": WEATHER_CONTRACT,
                "retrieved_at_utc": venue_retrieved,
                "venue_id": venue["venue_id"],
            }
        else:
            outdoor_by_season.setdefault(int(game["season"]), []).append(game)

    max_batch = int((config.get("weather_reconstruction") or {}).get("max_venues_per_archive_request", 20))
    if max_batch < 1 or max_batch > 100:
        raise CFBAcquisitionError("CFB_OPEN_METEO_BATCH_SIZE_INVALID")

    weather_metas: list[dict[str, Any]] = []
    weather_calls = 0
    weather_cache_hits = 0
    for season, season_games in sorted(outdoor_by_season.items()):
        venue_ids = sorted({resolved[str(game["game_id"])]["venue_id"] for game in season_games})
        for offset in range(0, len(venue_ids), max_batch):
            batch_ids = venue_ids[offset:offset + max_batch]
            batch_set = set(batch_ids)
            batch_venues = [dict(by_id[venue_id]) for venue_id in batch_ids]
            batch_games = [
                game for game in season_games
                if resolved[str(game["game_id"])]["venue_id"] in batch_set
            ]
            kickoff_dates = [_dt(game["start_ts"], "CFB_GAME_KICKOFF_INVALID").date() for game in batch_games]
            request_item = weather_request_fn(
                config=config,
                season=season,
                venues=batch_venues,
                start_date=min(kickoff_dates).isoformat(),
                end_date=max(kickoff_dates).isoformat(),
            )
            payload, meta, cached = fetch_public_weather_fn(
                request_item,
                cache_root=weather_cache_root,
                opener=opener,
            )
            weather_metas.append(dict(meta))
            if cached:
                weather_cache_hits += 1
            else:
                weather_calls += 1
            location_rows = _normalize_open_meteo_payload(payload, len(batch_venues))
            hourly_by_venue = {
                str(venue["venue_id"]): _hourly_index(location)
                for venue, location in zip(batch_venues, location_rows)
            }
            retrieved = str(meta["retrieved_at_utc"])
            for game in batch_games:
                gid = str(game["game_id"])
                venue_id = resolved[gid]["venue_id"]
                key = weather_hour_key(game["start_ts"])
                values = hourly_by_venue[venue_id].get(key)
                if values is None:
                    raise CFBAcquisitionError(f"CFB_OPEN_METEO_KICKOFF_HOUR_MISSING:{gid}:{key}")
                temp_f, wind_mph = values
                weather_by_game[gid] = {
                    "gameIndoors": False,
                    "windSpeed": wind_mph,
                    "temperature": temp_f,
                    "source": WEATHER_CONTRACT,
                    "retrieved_at_utc": retrieved,
                    "venue_id": venue_id,
                    "reanalysis_model": "era5",
                    "time_selection": "UTC_KICKOFF_HOUR_FLOOR_NO_INTERPOLATION",
                }

    missing = sorted(str(game["game_id"]) for game in games if str(game["game_id"]) not in weather_by_game)
    if missing:
        raise CFBAcquisitionError(f"CFB_RECONSTRUCTED_WEATHER_MISSING:{missing[0]}")
    return weather_by_game, weather_metas, weather_calls, weather_cache_hits
