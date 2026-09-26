"""CFB reconstructed acquire weather helpers (null-weather path).

Unresolved venues keep game rows with temp/wind null and source WEATHER_MISSING.
Those games are excluded from Open-Meteo batches only.

This module does not define CFBAcquisitionError. Callers pass error_cls and the
acquire script's normalize/hourly/hour-key functions so exception types and hour
matching cannot drift.

No Model_P / Truth Gate / promotion / eligibility / OFFICIAL authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, Type
from urllib.request import urlopen

from sportsedge.sports.cfb.venue_coordinates import venue_indexes

WEATHER_CONTRACT = "CFBD_VENUES_OPEN_METEO_ERA5_RECONSTRUCTED_CURRENT_PROVIDER_VINTAGE"
WEATHER_MISSING_SOURCE = "WEATHER_MISSING"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def build_weather_with_null_path(
    *,
    games: Sequence[Mapping[str, Any]],
    venues_raw: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
    weather_cache_root: Path,
    weather_request_fn: Callable,
    fetch_public_weather_fn: Callable,
    normalize_open_meteo_payload_fn: Callable,
    hourly_index_fn: Callable,
    weather_hour_key_fn: Callable,
    error_cls: Type[BaseException],
    opener: Callable = urlopen,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], int, int, list[str]]:
    """Keep all game rows. Unresolved venues get WEATHER_MISSING; not sent to Open-Meteo.

    Returns:
        weather_by_game, weather_metas, weather_calls, weather_cache_hits, weather_missing_game_ids
    """
    by_id, by_name = venue_indexes(venues_raw)
    if not by_id:
        raise error_cls("CFB_VENUES_EMPTY")

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
            "source": WEATHER_MISSING_SOURCE,
            "retrieved_at_utc": venue_retrieved,
            "venue_id": None,
            "weather_status": WEATHER_MISSING_SOURCE,
            "weather_missing": True,
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
                "weather_missing": False,
            }
        else:
            outdoor_by_season.setdefault(int(game["season"]), []).append(game)

    max_batch = int((config.get("weather_reconstruction") or {}).get("max_venues_per_archive_request", 20))
    if max_batch < 1 or max_batch > 100:
        raise error_cls("CFB_OPEN_METEO_BATCH_SIZE_INVALID")

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
            kickoff_dates = []
            for game in batch_games:
                text = str(game["start_ts"] or "").strip().replace("Z", "+00:00")
                parsed = datetime.fromisoformat(text)
                if parsed.tzinfo is None or parsed.utcoffset() is None:
                    raise error_cls("CFB_GAME_KICKOFF_INVALID")
                kickoff_dates.append(parsed.astimezone(timezone.utc).date())
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
            location_rows = normalize_open_meteo_payload_fn(payload, len(batch_venues))
            hourly_by_venue = {
                str(venue["venue_id"]): hourly_index_fn(location)
                for venue, location in zip(batch_venues, location_rows)
            }
            retrieved = str(meta["retrieved_at_utc"])
            for game in batch_games:
                gid = str(game["game_id"])
                venue_id = resolved[gid]["venue_id"]
                key = weather_hour_key_fn(game["start_ts"])
                values = hourly_by_venue[venue_id].get(key)
                if values is None:
                    raise error_cls(f"CFB_OPEN_METEO_KICKOFF_HOUR_MISSING:{gid}:{key}")
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
                    "weather_missing": False,
                }

    missing = sorted(str(game["game_id"]) for game in games if str(game["game_id"]) not in weather_by_game)
    if missing:
        raise error_cls(f"CFB_RECONSTRUCTED_WEATHER_MISSING:{missing[0]}")
    return (
        weather_by_game,
        weather_metas,
        weather_calls,
        weather_cache_hits,
        sorted(weather_missing),
    )
