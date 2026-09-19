#!/usr/bin/env python3
"""Acquire the frozen 2015-2025 reconstructed CFB selection inputs.

CFBD supplies games, FBS membership, venue metadata, and advanced metrics. Historical
weather is reconstructed from CFBD venue coordinates plus Open-Meteo ERA5 reanalysis
because CFBD's paid weather endpoint is not required by the frozen selection contract.

Raw provider responses are written only to caller-selected private cache paths. Public
attestations contain request/response hashes and governance state, never raw rows or
exact account/quota values.

This script never fits or evaluates a candidate and creates no Model_P, Truth Gate,
promotion, eligibility, staking, OFFICIAL, evidence-clock, PIT, or backfill authority.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import isfinite
import os
from pathlib import Path
import sys
import time
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.cfb.source import normalize_advanced_team_metrics

CONFIG = ROOT / "config/cfb_cfbd_reconstructed_selection_budget_v1.json"
CFBD_BASE = "https://api.collegefootballdata.com"
WEATHER_CONTRACT = "CFBD_VENUES_OPEN_METEO_ERA5_RECONSTRUCTED_CURRENT_PROVIDER_VINTAGE"


class CFBAcquisitionError(RuntimeError):
    pass


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(value: bytes) -> str:
    return sha256(value).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _zero_authority() -> dict[str, bool]:
    return {
        "attempt_consumed": False,
        "evaluation_performed": False,
        "historical_pit_created": False,
        "model_p_created": False,
        "truth_gate_authority": False,
        "promotion_authority": False,
        "staking_authority": False,
        "eligibility_changed": False,
        "official_authority": False,
        "backfill": False,
    }


def _validate_private_preflight(raw: object, expected_calls: int) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise CFBAcquisitionError("CFB_ACQUISITION_PRIVATE_PREFLIGHT_MISSING")
    if raw.get("schema_version") != "CFB_CFBD_PROVIDER_PREFLIGHT_V1":
        raise CFBAcquisitionError("CFB_ACQUISITION_PRIVATE_PREFLIGHT_SCHEMA_INVALID")
    if raw.get("status") != "VERIFIED_BEFORE_FIRST_REPLAY_CALL":
        raise CFBAcquisitionError("CFB_ACQUISITION_PREFLIGHT_NOT_VERIFIED")
    if raw.get("weather_transport_ready") is not True:
        raise CFBAcquisitionError("CFB_ACQUISITION_WEATHER_TRANSPORT_NOT_READY")
    if raw.get("cfbd_weather_required_for_selection") is not False:
        raise CFBAcquisitionError("CFB_ACQUISITION_CFBD_WEATHER_REQUIREMENT_INVALID")
    if str(raw.get("weather_source_contract") or "").strip() != WEATHER_CONTRACT:
        raise CFBAcquisitionError("CFB_ACQUISITION_WEATHER_CONTRACT_MISMATCH")
    if raw.get("historical_replay_calls_performed") != 0:
        raise CFBAcquisitionError("CFB_ACQUISITION_PREFLIGHT_REPLAY_CALL_LEAK")
    try:
        planned = int(raw["planned_new_calls"])
        reserve = int(raw["retry_reserve_calls"])
        remaining = int(raw["remaining_quota"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CFBAcquisitionError("CFB_ACQUISITION_PREFLIGHT_QUOTA_INVALID") from exc
    if planned != expected_calls:
        raise CFBAcquisitionError(f"CFB_ACQUISITION_PLAN_COUNT_MISMATCH:{planned}:{expected_calls}")
    if remaining < planned + reserve:
        raise CFBAcquisitionError("CFB_ACQUISITION_VERIFIED_QUOTA_INSUFFICIENT")
    authority = raw.get("authority")
    if not isinstance(authority, Mapping) or any(value is not False for value in authority.values()):
        raise CFBAcquisitionError("CFB_ACQUISITION_PREFLIGHT_AUTHORITY_LEAK")
    return raw


def _request(endpoint: str, params: Mapping[str, Any], provider_contract: str) -> dict[str, Any]:
    clean = {str(k): v for k, v in params.items() if v is not None}
    identity = {"endpoint": endpoint, "params": clean, "provider_contract": provider_contract}
    return {**identity, "query_sha256": _sha(_canonical_bytes(identity))}


def build_request_plan(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Build only the quota-bearing CFBD request plan."""
    start = int(config["selection_start_season"])
    end = int(config["selection_end_season"])
    prior = int(config["prior_fallback_season"])
    max_week = int(config["max_regular_week_planning_bound"])
    weather = config.get("weather_reconstruction") or {}
    venue_endpoint = str(weather.get("venue_endpoint") or "")
    if venue_endpoint != "/venues":
        raise CFBAcquisitionError("CFB_ACQUISITION_VENUE_ENDPOINT_INVALID")

    out: list[dict[str, Any]] = []
    for season in range(prior, end + 1):
        out.append(_request(
            "/games",
            {"year": season, "seasonType": "regular", "classification": "fbs"},
            "CFBD_GAMES_REGULAR_FBS_V1",
        ))
    for season in range(start, end + 1):
        out.append(_request(
            "/teams/fbs",
            {"year": season},
            "CFBD_FBS_MEMBERSHIP_V1",
        ))
    out.append(_request("/venues", {}, "CFBD_VENUES_LOCATION_DOME_V1"))
    for season in range(prior, end):
        out.append(_request(
            "/stats/season/advanced",
            {"year": season, "excludeGarbageTime": "true", "classification": "fbs"},
            "CFBD_STATS_SEASON_ADVANCED_ENDWEEK_V1",
        ))
    for season in range(start, end + 1):
        for end_week in range(1, max_week):
            out.append(_request(
                "/stats/season/advanced",
                {
                    "year": season,
                    "endWeek": end_week,
                    "excludeGarbageTime": "true",
                    "classification": "fbs",
                },
                "CFBD_STATS_SEASON_ADVANCED_ENDWEEK_V1",
            ))

    expected = int((config.get("planned_new_calls_upper_bound") or {}).get("total", -1))
    if len(out) != expected:
        raise CFBAcquisitionError(f"CFB_ACQUISITION_PLAN_CONFIG_DRIFT:{len(out)}:{expected}")
    keys = [row["query_sha256"] for row in out]
    if len(keys) != len(set(keys)):
        raise CFBAcquisitionError("CFB_ACQUISITION_PLAN_DUPLICATE_QUERY")
    return out


def _cache_paths(cache_root: Path, query_sha: str) -> tuple[Path, Path]:
    return cache_root / f"{query_sha}.json", cache_root / f"{query_sha}.meta.json"


def _load_verified_cache(*, cache_root: Path, query_sha: str) -> tuple[Any, dict[str, Any]] | None:
    body_path, meta_path = _cache_paths(cache_root, query_sha)
    if not body_path.is_file() or not meta_path.is_file():
        return None
    raw = body_path.read_bytes()
    meta = _load(meta_path)
    if not isinstance(meta, Mapping):
        raise CFBAcquisitionError(f"CFB_ACQUISITION_CACHE_META_INVALID:{query_sha}")
    if _sha(raw) != meta.get("response_sha256"):
        raise CFBAcquisitionError(f"CFB_ACQUISITION_CACHE_HASH_MISMATCH:{query_sha}")
    if meta.get("query_sha256") != query_sha:
        raise CFBAcquisitionError(f"CFB_ACQUISITION_CACHE_QUERY_MISMATCH:{query_sha}")
    return json.loads(raw.decode("utf-8")), dict(meta)


def _store_cache(*, cache_root: Path, query_sha: str, raw: bytes, meta: Mapping[str, Any]) -> None:
    body_path, meta_path = _cache_paths(cache_root, query_sha)
    cache_root.mkdir(parents=True, exist_ok=True)
    body_path.write_bytes(raw)
    meta_path.write_text(json.dumps(dict(meta), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _fetch_one(
    item: Mapping[str, Any],
    *,
    api_key: str,
    cache_root: Path,
    opener: Callable = urlopen,
    max_attempts: int = 3,
) -> tuple[Any, dict[str, Any], bool]:
    query_sha = str(item["query_sha256"])
    cached = _load_verified_cache(cache_root=cache_root, query_sha=query_sha)
    if cached is not None:
        payload, meta = cached
        return payload, meta, True

    key = str(api_key or "").strip()
    if not key:
        raise CFBAcquisitionError("CFBD_API_KEY_MISSING")
    params = item.get("params") or {}
    suffix = f"?{urlencode(params)}" if params else ""
    url = f"{CFBD_BASE}{item['endpoint']}{suffix}"
    request = Request(url, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    last: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            with opener(request, timeout=30) as response:
                raw = response.read()
            decoded = json.loads(raw.decode("utf-8"))
            meta = {
                "endpoint": item["endpoint"],
                "season": int(params["year"]) if "year" in params else None,
                "end_week": int(params["endWeek"]) if "endWeek" in params else None,
                "params": dict(params),
                "provider_contract": item["provider_contract"],
                "query_sha256": query_sha,
                "response_sha256": _sha(raw),
                "retrieved_at_utc": _now(),
            }
            _store_cache(cache_root=cache_root, query_sha=query_sha, raw=raw, meta=meta)
            return decoded, meta, False
        except Exception as exc:
            last = exc
            if attempt < max_attempts:
                time.sleep(2 ** (attempt - 1))
    raise CFBAcquisitionError(
        f"CFB_ACQUISITION_FETCH_FAILED:{item['endpoint']}:{type(last).__name__}"
    ) from last


def _weather_request(
    *,
    config: Mapping[str, Any],
    season: int,
    venues: Sequence[Mapping[str, Any]],
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    weather = config.get("weather_reconstruction") or {}
    endpoint = str(weather.get("archive_endpoint") or "")
    model = str(weather.get("archive_model") or "")
    variables = list(weather.get("hourly_variables") or [])
    if not endpoint.startswith("https://archive-api.open-meteo.com/"):
        raise CFBAcquisitionError("CFB_OPEN_METEO_ENDPOINT_INVALID")
    if model != "era5":
        raise CFBAcquisitionError("CFB_OPEN_METEO_MODEL_INVALID")
    if variables != ["temperature_2m", "wind_speed_10m"]:
        raise CFBAcquisitionError("CFB_OPEN_METEO_VARIABLE_CONTRACT_INVALID")
    if not venues:
        raise CFBAcquisitionError("CFB_OPEN_METEO_VENUE_BATCH_EMPTY")

    params = {
        "latitude": ",".join(f"{float(row['latitude']):.6f}" for row in venues),
        "longitude": ",".join(f"{float(row['longitude']):.6f}" for row in venues),
        "start_date": start_date,
        "end_date": end_date,
        "hourly": ",".join(variables),
        "temperature_unit": str(weather.get("temperature_unit") or ""),
        "wind_speed_unit": str(weather.get("wind_speed_unit") or ""),
        "timezone": "GMT",
        "models": model,
    }
    identity = {
        "endpoint": endpoint,
        "params": params,
        "provider_contract": WEATHER_CONTRACT,
        "season": int(season),
        "venue_ids": [str(row["venue_id"]) for row in venues],
    }
    return {**identity, "query_sha256": _sha(_canonical_bytes(identity))}


def _fetch_public_weather(
    item: Mapping[str, Any],
    *,
    cache_root: Path,
    opener: Callable = urlopen,
    max_attempts: int = 3,
) -> tuple[Any, dict[str, Any], bool]:
    query_sha = str(item["query_sha256"])
    cached = _load_verified_cache(cache_root=cache_root, query_sha=query_sha)
    if cached is not None:
        payload, meta = cached
        return payload, meta, True

    url = f"{item['endpoint']}?{urlencode(item['params'])}"
    request = Request(url, headers={"Accept": "application/json"})
    last: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            with opener(request, timeout=60) as response:
                raw = response.read()
            decoded = json.loads(raw.decode("utf-8"))
            meta = {
                "endpoint": item["endpoint"],
                "season": int(item["season"]),
                "venue_ids": list(item["venue_ids"]),
                "params": dict(item["params"]),
                "provider_contract": item["provider_contract"],
                "query_sha256": query_sha,
                "response_sha256": _sha(raw),
                "retrieved_at_utc": _now(),
            }
            _store_cache(cache_root=cache_root, query_sha=query_sha, raw=raw, meta=meta)
            return decoded, meta, False
        except Exception as exc:
            last = exc
            if attempt < max_attempts:
                time.sleep(2 ** (attempt - 1))
    raise CFBAcquisitionError(f"CFB_OPEN_METEO_FETCH_FAILED:{type(last).__name__}") from last


def _points_by_team(games: list[Mapping[str, Any]], through_week: int) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in games:
        if row.get("completed") is not True:
            continue
        try:
            week = int(row.get("week", 0))
        except (TypeError, ValueError):
            continue
        if week > through_week:
            continue
        for team_key, points_key in (("homeTeam", "homePoints"), ("awayTeam", "awayPoints")):
            team = str(row.get(team_key) or "").strip()
            points = row.get(points_key)
            if team and points is not None:
                out[team] = out.get(team, 0.0) + float(points)
    return out


def _membership_set(rows: list[Mapping[str, Any]]) -> set[str]:
    return {
        str(row.get("school") or "").strip()
        for row in rows
        if str(row.get("school") or "").strip()
    }


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


def _venue_coordinates(raw: Mapping[str, Any]) -> tuple[float, float]:
    lat = raw.get("latitude")
    lon = raw.get("longitude")
    if lat is None or lon is None:
        location = raw.get("location")
        if isinstance(location, Mapping):
            lat = location.get("y")
            lon = location.get("x")
    try:
        lat_f, lon_f = float(lat), float(lon)
    except (TypeError, ValueError) as exc:
        raise CFBAcquisitionError("CFB_VENUE_COORDINATES_MISSING") from exc
    if not isfinite(lat_f) or not isfinite(lon_f) or not (-90 <= lat_f <= 90) or not (-180 <= lon_f <= 180):
        raise CFBAcquisitionError("CFB_VENUE_COORDINATES_INVALID")
    return lat_f, lon_f


def _venue_indexes(rows: Sequence[Mapping[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}
    for raw in rows:
        venue_id = str(raw.get("id") or "").strip()
        name = str(raw.get("name") or "").strip()
        dome = raw.get("dome")
        if not venue_id or not name or type(dome) is not bool:
            continue
        lat, lon = _venue_coordinates(raw)
        normalized = {
            "venue_id": venue_id,
            "name": name,
            "dome": dome,
            "latitude": lat,
            "longitude": lon,
        }
        by_id[venue_id] = normalized
        folded = name.casefold()
        if folded in by_name and by_name[folded]["venue_id"] != venue_id:
            raise CFBAcquisitionError(f"CFB_VENUE_NAME_AMBIGUOUS:{name}")
        by_name[folded] = normalized
    if not by_id:
        raise CFBAcquisitionError("CFB_VENUES_EMPTY")
    return by_id, by_name


def _resolve_venue(
    game: Mapping[str, Any],
    *,
    by_id: Mapping[str, Mapping[str, Any]],
    by_name: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    venue_id = str(game.get("venueId") or game.get("venue_id") or "").strip()
    if venue_id and venue_id in by_id:
        return dict(by_id[venue_id])
    venue_name = str(game.get("venue") or "").strip()
    if venue_name and venue_name.casefold() in by_name:
        return dict(by_name[venue_name.casefold()])
    raise CFBAcquisitionError(f"CFB_GAME_VENUE_UNRESOLVED:{game.get('id') or game.get('game_id')}")


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


def _weather_hour_key(start_ts: object) -> str:
    kickoff = _dt(start_ts, "CFB_GAME_KICKOFF_INVALID")
    floored = kickoff.replace(minute=0, second=0, microsecond=0)
    return floored.strftime("%Y-%m-%dT%H:00")


def _build_weather(
    *,
    games: Sequence[Mapping[str, Any]],
    venues_raw: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
    weather_cache_root: Path,
    opener: Callable = urlopen,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], int, int]:
    by_id, by_name = _venue_indexes(venues_raw)
    resolved: dict[str, dict[str, Any]] = {}
    for game in games:
        gid = str(game["game_id"])
        resolved[gid] = _resolve_venue(game, by_id=by_id, by_name=by_name)

    weather_by_game: dict[str, dict[str, Any]] = {}
    outdoor_by_season: dict[int, list[Mapping[str, Any]]] = {}
    venue_retrieved = _now()
    for game in games:
        gid = str(game["game_id"])
        venue = resolved[gid]
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
            request_item = _weather_request(
                config=config,
                season=season,
                venues=batch_venues,
                start_date=min(kickoff_dates).isoformat(),
                end_date=max(kickoff_dates).isoformat(),
            )
            payload, meta, cached = _fetch_public_weather(
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
                key = _weather_hour_key(game["start_ts"])
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


def _build_private_payload(
    *,
    preflight: Mapping[str, Any],
    fetched: Mapping[str, tuple[Any, Mapping[str, Any]]],
    plan: list[Mapping[str, Any]],
    config: Mapping[str, Any],
    weather_cache_root: Path,
    weather_opener: Callable = urlopen,
) -> tuple[dict[str, Any], int, int]:
    by_identity: dict[tuple[str, int | None, int | None], tuple[Any, Mapping[str, Any]]] = {}
    for item in plan:
        params = item["params"]
        year = int(params["year"]) if "year" in params else None
        end_week = int(params["endWeek"]) if "endWeek" in params else None
        by_identity[(str(item["endpoint"]), year, end_week)] = fetched[str(item["query_sha256"])]

    games_by_season: dict[int, list[Mapping[str, Any]]] = {}
    membership_by_season: dict[int, list[Mapping[str, Any]]] = {}
    for season in range(2014, 2026):
        raw, _meta = by_identity[("/games", season, None)]
        if not isinstance(raw, list):
            raise CFBAcquisitionError(f"CFB_ACQUISITION_GAMES_NOT_LIST:{season}")
        games_by_season[season] = [dict(row) for row in raw if isinstance(row, Mapping)]
    for season in range(2015, 2026):
        raw, _meta = by_identity[("/teams/fbs", season, None)]
        if not isinstance(raw, list):
            raise CFBAcquisitionError(f"CFB_ACQUISITION_MEMBERSHIP_NOT_LIST:{season}")
        membership_by_season[season] = [dict(row) for row in raw if isinstance(row, Mapping)]

    venues_raw, _venues_meta = by_identity[("/venues", None, None)]
    if not isinstance(venues_raw, list):
        raise CFBAcquisitionError("CFB_ACQUISITION_VENUES_NOT_LIST")

    games: list[dict[str, Any]] = []
    for season in range(2015, 2026):
        membership = _membership_set(membership_by_season[season])
        for row in games_by_season[season]:
            if row.get("completed") is not True:
                continue
            home = str(row.get("homeTeam") or "").strip()
            away = str(row.get("awayTeam") or "").strip()
            if home not in membership or away not in membership:
                continue
            if row.get("homePoints") is None or row.get("awayPoints") is None:
                raise CFBAcquisitionError(f"CFB_ACQUISITION_COMPLETED_SCORE_MISSING:{row.get('id')}")
            game_id = str(row.get("id") or "").strip()
            if not game_id:
                raise CFBAcquisitionError("CFB_ACQUISITION_GAME_ID_MISSING")
            games.append({
                "game_id": game_id,
                "season": int(row.get("season", season)),
                "week": int(row.get("week")),
                "start_ts": row.get("startDate"),
                "home_team": home,
                "away_team": away,
                "neutral_site": bool(row.get("neutralSite", False)),
                "venue_id": row.get("venueId"),
                "venue": row.get("venue"),
                "home_score": row.get("homePoints"),
                "away_score": row.get("awayPoints"),
                **({
                    "regulation_home_score": sum(float(x) for x in row.get("homeLineScores")[:4]),
                    "regulation_away_score": sum(float(x) for x in row.get("awayLineScores")[:4]),
                } if (
                    isinstance(row.get("homeLineScores"), list) and len(row.get("homeLineScores")) >= 4
                    and isinstance(row.get("awayLineScores"), list) and len(row.get("awayLineScores")) >= 4
                    and all(x is not None for x in row.get("homeLineScores")[:4])
                    and all(x is not None for x in row.get("awayLineScores")[:4])
                ) else {}),
            })

    weather_by_game, weather_metas, weather_calls, weather_cache_hits = _build_weather(
        games=games,
        venues_raw=[dict(row) for row in venues_raw if isinstance(row, Mapping)],
        config=config,
        weather_cache_root=weather_cache_root,
        opener=weather_opener,
    )

    metrics: list[dict[str, Any]] = []
    for season in range(2014, 2025):
        advanced, meta = by_identity[("/stats/season/advanced", season, None)]
        if not isinstance(advanced, list):
            raise CFBAcquisitionError(f"CFB_ACQUISITION_ADVANCED_NOT_LIST:{season}:prior")
        points = _points_by_team(games_by_season[season], through_week=99)
        for raw in advanced:
            if isinstance(raw, Mapping):
                metrics.append(normalize_advanced_team_metrics(
                    raw,
                    through_week=99,
                    feature_asof_ts=str(meta["retrieved_at_utc"]),
                    season_points=points,
                    sample_source="PRIOR_SEASON_FALLBACK",
                ).to_dict())

    for season in range(2015, 2026):
        for end_week in range(1, 20):
            advanced, meta = by_identity[("/stats/season/advanced", season, end_week)]
            if not isinstance(advanced, list):
                raise CFBAcquisitionError(f"CFB_ACQUISITION_ADVANCED_NOT_LIST:{season}:{end_week}")
            points = _points_by_team(games_by_season[season], through_week=end_week)
            for raw in advanced:
                if isinstance(raw, Mapping):
                    metrics.append(normalize_advanced_team_metrics(
                        raw,
                        through_week=end_week,
                        feature_asof_ts=str(meta["retrieved_at_utc"]),
                        season_points=points,
                        sample_source="CURRENT_SEASON_PRIOR_WEEKS",
                    ).to_dict())

    responses = [dict(fetched[str(item["query_sha256"])][1]) for item in plan] + weather_metas
    source_manifest = {
        "schema": "CFB_RECONSTRUCTED_SOURCE_MANIFEST_V1",
        "provenance_class": "RECONSTRUCTED_HISTORICAL_NOT_PIT",
        "providers": ["CollegeFootballData", "Open-Meteo ERA5"],
        "raw_provider_data_persisted_publicly": False,
        "response_count": len(responses),
        "responses": responses,
        "historical_pit_created": False,
    }
    payload = {
        "schema": "CFB_RECONSTRUCTED_ACQUISITION_PAYLOAD_V1",
        "private_preflight": dict(preflight),
        "source_manifest": source_manifest,
        "games": games,
        "metrics": metrics,
        "weather_by_game": weather_by_game,
        "fbs_membership_by_season": {str(k): v for k, v in membership_by_season.items()},
        "weather_source_contract": WEATHER_CONTRACT,
    }
    return payload, weather_calls, weather_cache_hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-preflight", type=Path, required=True)
    parser.add_argument("--private-cache-root", type=Path, required=True)
    parser.add_argument("--private-payload-out", type=Path, required=True)
    parser.add_argument("--public-attestation-out", type=Path, required=True)
    args = parser.parse_args(argv)

    config = _load(CONFIG)
    plan = build_request_plan(config)
    preflight = _validate_private_preflight(_load(args.private_preflight), len(plan))
    api_key = os.environ.get("CFBD_API_KEY", "")
    if not api_key.strip():
        raise SystemExit("CFBD_API_KEY_MISSING")

    fetched: dict[str, tuple[Any, Mapping[str, Any]]] = {}
    cfbd_cache_hits = 0
    cfbd_network_calls = 0
    weather_network_calls = 0
    weather_cache_hits = 0
    try:
        for item in plan:
            payload, meta, cached = _fetch_one(
                item,
                api_key=api_key,
                cache_root=args.private_cache_root / "cfbd",
            )
            fetched[str(item["query_sha256"])] = (payload, meta)
            if cached:
                cfbd_cache_hits += 1
            else:
                cfbd_network_calls += 1

        private_payload, weather_network_calls, weather_cache_hits = _build_private_payload(
            preflight=preflight,
            fetched=fetched,
            plan=plan,
            config=config,
            weather_cache_root=args.private_cache_root / "open_meteo",
        )
    except Exception as exc:
        args.public_attestation_out.parent.mkdir(parents=True, exist_ok=True)
        blocked = {
            "schema": "CFB_RECONSTRUCTED_ACQUISITION_PUBLIC_V1",
            "status": "BLOCKED_ACQUISITION",
            "reason": f"{type(exc).__name__}:{exc}",
            "planned_cfbd_request_count": len(plan),
            "cfbd_network_calls_performed": cfbd_network_calls,
            "cfbd_verified_cache_hits": cfbd_cache_hits,
            "weather_network_calls_performed": weather_network_calls,
            "weather_verified_cache_hits": weather_cache_hits,
            "raw_provider_data_persisted_publicly": False,
            "authority": _zero_authority(),
        }
        args.public_attestation_out.write_text(
            json.dumps(blocked, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(blocked, sort_keys=True))
        return 2

    args.private_payload_out.parent.mkdir(parents=True, exist_ok=True)
    args.private_payload_out.write_text(
        json.dumps(private_payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    response_hashes = [row["response_sha256"] for row in private_payload["source_manifest"]["responses"]]
    attestation = {
        "schema": "CFB_RECONSTRUCTED_ACQUISITION_PUBLIC_V1",
        "status": "ACQUISITION_MATERIALIZED_PRIVATELY",
        "provider_preflight_verified": True,
        "cfbd_weather_entitlement_required": False,
        "weather_transport_verified": True,
        "weather_source_contract": WEATHER_CONTRACT,
        "quota_plan_verified": True,
        "planned_cfbd_request_count": len(plan),
        "cfbd_network_calls_performed": cfbd_network_calls,
        "cfbd_verified_cache_hits": cfbd_cache_hits,
        "weather_network_calls_performed": weather_network_calls,
        "weather_verified_cache_hits": weather_cache_hits,
        "source_response_count": len(response_hashes),
        "source_response_hash_set_sha256": _sha(_canonical_bytes(sorted(response_hashes))),
        "raw_provider_data_persisted_publicly": False,
        "authority": _zero_authority(),
    }
    args.public_attestation_out.parent.mkdir(parents=True, exist_ok=True)
    args.public_attestation_out.write_text(
        json.dumps(attestation, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(attestation, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
