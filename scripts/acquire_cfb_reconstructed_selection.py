#!/usr/bin/env python3
"""Acquire the frozen 2015-2025 reconstructed CFB selection inputs.

CFBD supplies games, FBS membership, venues, and advanced metrics. Historical
weather is reconstructed separately from CFBD venue metadata plus Open-Meteo ERA5
reanalysis. All raw responses remain runner-private and are hash-bound in the
source manifest. This lane is RECONSTRUCTED_HISTORICAL_NOT_PIT and has no
promotion authority.

This script never fits or evaluates a candidate and creates no Model_P, Truth Gate,
promotion, eligibility, staking, OFFICIAL, evidence-clock, PIT, or backfill authority.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Mapping, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.cfb.reconstructed_weather import (
    OPEN_METEO_ARCHIVE_ROOT,
    WEATHER_CONTRACT,
    archive_url,
    parse_archive_batch,
    parse_venues,
    weather_row,
)
from sportsedge.sports.cfb.source import normalize_advanced_team_metrics

CONFIG = ROOT / "config/cfb_cfbd_reconstructed_selection_budget_v1.json"
CFBD_BASE = "https://api.collegefootballdata.com"


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
        raise CFBAcquisitionError(
            f"CFB_ACQUISITION_PLAN_COUNT_MISMATCH:{planned}:{expected_calls}"
        )
    if remaining < planned + reserve:
        raise CFBAcquisitionError("CFB_ACQUISITION_VERIFIED_QUOTA_INSUFFICIENT")
    authority = raw.get("authority")
    if not isinstance(authority, Mapping) or any(value is not False for value in authority.values()):
        raise CFBAcquisitionError("CFB_ACQUISITION_PREFLIGHT_AUTHORITY_LEAK")
    return raw


def _request(endpoint: str, params: Mapping[str, Any], provider_contract: str) -> dict[str, Any]:
    clean = {str(k): v for k, v in params.items() if v is not None}
    identity = {
        "endpoint": endpoint,
        "params": clean,
        "provider_contract": provider_contract,
    }
    return {
        **identity,
        "query_sha256": _sha(_canonical_bytes(identity)),
    }


def build_request_plan(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    start = int(config["selection_start_season"])
    end = int(config["selection_end_season"])
    prior = int(config["prior_fallback_season"])
    max_week = int(config["max_regular_week_planning_bound"])
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
    out.append(_request("/venues", {}, "CFBD_VENUES_GEOMETRY_DOME_V1"))
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


def _read_cache(cache_root: Path, query_sha: str) -> tuple[Any, dict[str, Any]] | None:
    body_path, meta_path = _cache_paths(cache_root, query_sha)
    if not (body_path.is_file() and meta_path.is_file()):
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


def _write_cache(cache_root: Path, query_sha: str, raw: bytes, meta: Mapping[str, Any]) -> None:
    cache_root.mkdir(parents=True, exist_ok=True)
    body_path, meta_path = _cache_paths(cache_root, query_sha)
    body_path.write_bytes(raw)
    meta_path.write_text(json.dumps(dict(meta), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _fetch_one(
    item: Mapping[str, Any],
    *,
    api_key: str,
    cache_root: Path,
    opener=urlopen,
    max_attempts: int = 3,
) -> tuple[Any, dict[str, Any], bool]:
    query_sha = str(item["query_sha256"])
    cached = _read_cache(cache_root, query_sha)
    if cached is not None:
        payload, meta = cached
        return payload, meta, True

    key = str(api_key or "").strip()
    if not key:
        raise CFBAcquisitionError("CFBD_API_KEY_MISSING")
    params = item.get("params") or {}
    query = urlencode(params)
    url = f"{CFBD_BASE}{item['endpoint']}" + (f"?{query}" if query else "")
    request = Request(url, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    last: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            with opener(request, timeout=30) as response:
                raw = response.read()
            decoded = json.loads(raw.decode("utf-8"))
            retrieved = _now()
            meta = {
                "endpoint": item["endpoint"],
                "season": int(params["year"]) if "year" in params else None,
                "end_week": int(params["endWeek"]) if "endWeek" in params else None,
                "params": dict(params),
                "provider_contract": item["provider_contract"],
                "query_sha256": query_sha,
                "response_sha256": _sha(raw),
                "retrieved_at_utc": retrieved,
            }
            _write_cache(cache_root, query_sha, raw, meta)
            return decoded, meta, False
        except Exception as exc:
            last = exc
            if attempt < max_attempts:
                time.sleep(2 ** (attempt - 1))
    raise CFBAcquisitionError(
        f"CFB_ACQUISITION_FETCH_FAILED:{item['endpoint']}:{type(last).__name__}"
    ) from last


def _fetch_archive_batch(
    *,
    venues: Sequence[Any],
    season: int,
    week: int,
    start_date: str,
    end_date: str,
    cache_root: Path,
    opener=urlopen,
    max_attempts: int = 3,
) -> tuple[Any, dict[str, Any], bool]:
    url = archive_url(venues, start_date, end_date)
    identity = {
        "endpoint": OPEN_METEO_ARCHIVE_ROOT,
        "season": int(season),
        "week": int(week),
        "start_date": start_date,
        "end_date": end_date,
        "venue_ids": [int(venue.venue_id) for venue in venues],
        "provider_contract": WEATHER_CONTRACT,
        "archive_model": "era5",
        "hourly": ["temperature_2m", "wind_speed_10m"],
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "timezone": "GMT",
    }
    query_sha = _sha(_canonical_bytes(identity))
    cached = _read_cache(cache_root, query_sha)
    if cached is not None:
        payload, meta = cached
        return payload, meta, True

    request = Request(url, headers={"Accept": "application/json", "User-Agent": "SportsEdge-CFB-reconstructed-weather/1"})
    last: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            with opener(request, timeout=60) as response:
                raw = response.read()
            decoded = json.loads(raw.decode("utf-8"))
            retrieved = _now()
            meta = {
                "endpoint": OPEN_METEO_ARCHIVE_ROOT,
                "season": int(season),
                "end_week": int(week),
                "params": {
                    "start_date": start_date,
                    "end_date": end_date,
                    "venue_ids": identity["venue_ids"],
                    "archive_model": "era5",
                },
                "provider_contract": WEATHER_CONTRACT,
                "query_sha256": query_sha,
                "response_sha256": _sha(raw),
                "retrieved_at_utc": retrieved,
            }
            _write_cache(cache_root, query_sha, raw, meta)
            return decoded, meta, False
        except Exception as exc:
            last = exc
            if attempt < max_attempts:
                time.sleep(2 ** (attempt - 1))
    raise CFBAcquisitionError(
        f"CFB_OPEN_METEO_ARCHIVE_FETCH_FAILED:{season}:{week}:{type(last).__name__}"
    ) from last


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
    return {str(row.get("school") or "").strip() for row in rows if str(row.get("school") or "").strip()}


def _chunks(values: Sequence[Any], size: int) -> list[list[Any]]:
    if size <= 0:
        raise CFBAcquisitionError("CFB_OPEN_METEO_BATCH_SIZE_INVALID")
    return [list(values[index:index + size]) for index in range(0, len(values), size)]


def _parse_start(value: object) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CFBAcquisitionError("CFB_ACQUISITION_GAME_START_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CFBAcquisitionError("CFB_ACQUISITION_GAME_START_INVALID")
    return parsed.astimezone(timezone.utc)


def _build_private_payload(
    *,
    preflight: Mapping[str, Any],
    fetched: Mapping[str, tuple[Any, Mapping[str, Any]]],
    plan: list[Mapping[str, Any]],
    config: Mapping[str, Any],
    cache_root: Path,
    archive_opener=urlopen,
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

    venues_raw, venues_meta = by_identity[("/venues", None, None)]
    if not isinstance(venues_raw, list):
        raise CFBAcquisitionError("CFB_ACQUISITION_VENUES_NOT_LIST")
    venues = parse_venues([dict(row) for row in venues_raw if isinstance(row, Mapping)])

    selected_raw_games: list[Mapping[str, Any]] = []
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
            venue_id_raw = row.get("venueId")
            if venue_id_raw is None:
                raise CFBAcquisitionError(f"CFB_ACQUISITION_VENUE_ID_MISSING:{game_id}")
            try:
                venue_id = int(venue_id_raw)
            except (TypeError, ValueError) as exc:
                raise CFBAcquisitionError(f"CFB_ACQUISITION_VENUE_ID_INVALID:{game_id}") from exc
            if venue_id not in venues:
                raise CFBAcquisitionError(f"CFB_ACQUISITION_VENUE_UNKNOWN:{game_id}:{venue_id}")
            selected_raw_games.append(row)
            games.append({
                "game_id": game_id,
                "season": int(row.get("season", season)),
                "week": int(row.get("week")),
                "start_ts": row.get("startDate"),
                "home_team": home,
                "away_team": away,
                "neutral_site": bool(row.get("neutralSite", False)),
                "venue": row.get("venue"),
                "home_score": row.get("homePoints"),
                "away_score": row.get("awayPoints"),
            })

    weather_cfg = config.get("weather_reconstruction") or {}
    batch_size = int(weather_cfg.get("max_venues_per_archive_request", 20))
    outdoor_groups: dict[tuple[int, int], list[Mapping[str, Any]]] = {}
    weather_by_game: dict[str, dict[str, Any]] = {}
    for row in selected_raw_games:
        venue = venues[int(row["venueId"])]
        gid = str(row["id"])
        if venue.dome:
            weather_by_game[gid] = weather_row(
                game=row,
                venue=venue,
                archive_grid=None,
                retrieved_at_utc=str(venues_meta["retrieved_at_utc"]),
            )
        else:
            key = (int(row["season"]), int(row["week"]))
            outdoor_groups.setdefault(key, []).append(row)

    weather_metas: list[dict[str, Any]] = []
    archive_network_calls = 0
    archive_cache_hits = 0
    for (season, week), rows in sorted(outdoor_groups.items()):
        venue_ids = sorted({int(row["venueId"]) for row in rows})
        for ids in _chunks(venue_ids, batch_size):
            specs = [venues[vid] for vid in ids]
            idset = set(ids)
            scoped = [row for row in rows if int(row["venueId"]) in idset]
            starts = [_parse_start(row.get("startDate")) for row in scoped]
            start_date = min(starts).date().isoformat()
            end_date = max(starts).date().isoformat()
            payload, meta, cached = _fetch_archive_batch(
                venues=specs,
                season=season,
                week=week,
                start_date=start_date,
                end_date=end_date,
                cache_root=cache_root,
                opener=archive_opener,
            )
            if cached:
                archive_cache_hits += 1
            else:
                archive_network_calls += 1
            weather_metas.append(dict(meta))
            grids = parse_archive_batch(payload, specs)
            for row in scoped:
                venue = venues[int(row["venueId"])]
                weather_by_game[str(row["id"])] = weather_row(
                    game=row,
                    venue=venue,
                    archive_grid=grids[venue.venue_id],
                    retrieved_at_utc=str(meta["retrieved_at_utc"]),
                )

    if len(weather_by_game) != len(selected_raw_games):
        raise CFBAcquisitionError(
            f"CFB_ACQUISITION_WEATHER_COVERAGE_INCOMPLETE:{len(weather_by_game)}:{len(selected_raw_games)}"
        )

    metrics: list[dict[str, Any]] = []
    for season in range(2014, 2025):
        advanced, meta = by_identity[("/stats/season/advanced", season, None)]
        if not isinstance(advanced, list):
            raise CFBAcquisitionError(f"CFB_ACQUISITION_ADVANCED_NOT_LIST:{season}:prior")
        points = _points_by_team(games_by_season[season], through_week=99)
        for raw in advanced:
            if not isinstance(raw, Mapping):
                continue
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
                if not isinstance(raw, Mapping):
                    continue
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
    return ({
        "schema": "CFB_RECONSTRUCTED_ACQUISITION_PAYLOAD_V1",
        "private_preflight": dict(preflight),
        "source_manifest": source_manifest,
        "games": games,
        "metrics": metrics,
        "weather_by_game": weather_by_game,
        "fbs_membership_by_season": {str(k): v for k, v in membership_by_season.items()},
        "weather_source_contract": WEATHER_CONTRACT,
    }, archive_network_calls, archive_cache_hits)


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
                cache_root=args.private_cache_root,
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
            cache_root=args.private_cache_root,
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
            "public_weather_network_calls_performed": weather_network_calls,
            "public_weather_verified_cache_hits": weather_cache_hits,
            "weather_source_contract": WEATHER_CONTRACT,
            "cfbd_weather_entitlement_required": False,
            "raw_provider_data_persisted_publicly": False,
            "authority": _zero_authority(),
        }
        args.public_attestation_out.write_text(json.dumps(blocked, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(blocked, sort_keys=True))
        return 2

    args.private_payload_out.parent.mkdir(parents=True, exist_ok=True)
    args.private_payload_out.write_text(json.dumps(private_payload, sort_keys=True) + "\n", encoding="utf-8")
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
        "public_weather_network_calls_performed": weather_network_calls,
        "public_weather_verified_cache_hits": weather_cache_hits,
        "source_response_count": len(response_hashes),
        "source_response_hash_set_sha256": _sha(_canonical_bytes(sorted(response_hashes))),
        "raw_provider_data_persisted_publicly": False,
        "authority": _zero_authority(),
    }
    args.public_attestation_out.parent.mkdir(parents=True, exist_ok=True)
    args.public_attestation_out.write_text(json.dumps(attestation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(attestation, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
