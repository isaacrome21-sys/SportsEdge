#!/usr/bin/env python3
"""Acquire frozen public CFB SportsDataverse + historical-weather inputs.

No candidate is fit or evaluated here. Sportsbook APIs and CFBD credentials are not
used. Historical weather is reconstructed from a pinned public stadium snapshot plus
Open-Meteo Archive and fails closed on missing venue or hourly coverage.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from hashlib import sha256
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.cfb.sportsdataverse_acquisition import acquisition_plan
from sportsedge.sports.cfb.sportsdataverse_csv import parse_csv
from sportsedge.sports.cfb.sportsdataverse_history import regular_fbs_schedule_rows
from sportsedge.sports.cfb.sportsdataverse_receipts import receipt, validate_receipts
from sportsedge.sports.cfb.sportsdataverse_weather_receipts import bind_weather_rows
from sportsedge.sports.cfb.sportsdataverse_weather_transport import (
    BASE_URL as WEATHER_URL,
    SOURCE_ID as WEATHER_SOURCE_ID,
    VENUE_SOURCE_COMMIT,
    VENUE_SOURCE_GIT_BLOB_SHA1,
    VENUE_SOURCE_PATH,
    VENUE_SOURCE_REPOSITORY,
    VENUE_SOURCE_SHA256,
    VENUE_SOURCE_URL,
    kickoff_date,
    request_params,
    resolve_venue,
    select_kickoff_hour,
    venue_indexes,
)

UA = "SportsEdge-CFB-SDV/1"
FROZEN_FIRST_ROW_SEASON = 2016
FROZEN_END_SEASON = 2025


def _get(url: str, *, headers: dict[str, str] | None = None, attempts: int = 4) -> bytes:
    last = None
    for attempt in range(attempts):
        try:
            req = Request(url, headers={"User-Agent": UA, **(headers or {})})
            with urlopen(req, timeout=120) as response:
                return response.read()
        except Exception as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"CFB_SDV_HTTP_FAILED:{url}") from last


def _strict_true(value) -> bool:
    if value is True:
        return True
    return str(value or "").strip().lower() in {"true", "1", "t"}


def _download_asset(item, root: Path):
    raw = _get(item.url)
    root.mkdir(parents=True, exist_ok=True)
    path = root / item.filename
    path.write_bytes(raw)
    rr = receipt(item, raw)
    schedule_rows = None
    if item.dataset == "cfb_schedules":
        schedule_rows, _ = parse_csv(
            raw,
            dataset=item.dataset,
            season=item.season,
            source_url=item.url,
            raw_csv_sha256=rr.sha256,
        )
    return item, rr, schedule_rows


def _evaluated_games(schedules: list[dict]) -> list[dict]:
    out = []
    for raw in regular_fbs_schedule_rows(schedules):
        season = int(raw["season"])
        if not FROZEN_FIRST_ROW_SEASON <= season <= FROZEN_END_SEASON:
            continue
        if not _strict_true(raw.get("completed")):
            continue
        gid = int(raw["game_id"])
        try:
            venue_id = int(float(str(raw.get("venue_id") or "").strip()))
        except ValueError as exc:
            raise RuntimeError(f"CFB_SDV_VENUE_ID_REQUIRED:{gid}") from exc
        kickoff = str(raw.get("start_date") or "").strip()
        if not kickoff:
            raise RuntimeError(f"CFB_SDV_START_DATE_REQUIRED:{gid}")
        out.append({
            "game_id": gid,
            "season": season,
            "venue_id": venue_id,
            "venue_name": str(raw.get("venue") or "").strip(),
            "start_date": kickoff,
        })
    if not out:
        raise RuntimeError("CFB_SDV_EVALUATED_GAMES_EMPTY")
    return sorted(out, key=lambda r: (r["season"], r["game_id"]))


def _window_job(*, season: int, venue: dict, games: list[dict]):
    dates = [date.fromisoformat(kickoff_date(g["start_date"])) for g in games]
    start = min(dates)
    end = max(dates) + timedelta(days=1)
    params = request_params(
        latitude=float(venue["latitude"]),
        longitude=float(venue["longitude"]),
        start_date=start.isoformat(),
        end_date=end.isoformat(),
    )
    raw = _get(WEATHER_URL + "?" + urlencode(params))
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"CFB_SDV_WEATHER_JSON_INVALID:{season}:{venue['venue_id']}"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError(
            f"CFB_SDV_WEATHER_JSON_MAPPING_REQUIRED:{season}:{venue['venue_id']}"
        )
    rows = [
        select_kickoff_hour(
            payload,
            game_id=g["game_id"],
            kickoff_utc=g["start_date"],
            game_indoor=False,
        )
        for g in games
    ]
    bound = bind_weather_rows(raw, rows, source_id=WEATHER_SOURCE_ID)
    return rows, {
        "season": season,
        "stadium_id": str(venue["stadium_id"]),
        "cfbd_venue_id": venue.get("venue_id"),
        "request": params,
        **bound.to_dict(),
    }


def _historical_weather(*, games: list[dict], venue_raw: bytes, workers: int):
    by_id, by_name = venue_indexes(venue_raw)
    rows: list[dict] = []
    grouped: dict[tuple[int, str], dict] = {}
    resolutions = {"CFBD_VENUE_ID": 0, "PINNED_EXACT_NAME_OR_ALIAS": 0}

    for game in games:
        try:
            venue, resolution = resolve_venue(
                by_id=by_id,
                by_name=by_name,
                venue_id=int(game["venue_id"]),
                venue_name=str(game.get("venue_name") or ""),
            )
        except Exception as exc:
            raise RuntimeError(
                "CFB_SDV_HISTORICAL_VENUE_INCOMPLETE:"
                f"{game['game_id']}:{game['venue_id']}:{game.get('venue_name','')}"
            ) from exc
        resolutions[resolution] = resolutions.get(resolution, 0) + 1
        if venue["game_indoor"]:
            rows.append(
                select_kickoff_hour(
                    {},
                    game_id=game["game_id"],
                    kickoff_utc=game["start_date"],
                    game_indoor=True,
                )
            )
        else:
            key = (int(game["season"]), str(venue["stadium_id"]))
            bucket = grouped.setdefault(key, {"venue": venue, "games": []})
            bucket["games"].append(game)

    jobs = []
    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
        for (season, _stadium_id), bucket in sorted(grouped.items()):
            jobs.append(
                pool.submit(
                    _window_job,
                    season=season,
                    venue=bucket["venue"],
                    games=bucket["games"],
                )
            )
        receipts = []
        for future in jobs:
            part, rec = future.result()
            rows.extend(part)
            receipts.append(rec)

    rows.sort(key=lambda r: int(r["game_id"]))
    expected = {int(g["game_id"]) for g in games}
    observed = [int(r["game_id"]) for r in rows]
    if len(observed) != len(set(observed)):
        raise RuntimeError("CFB_SDV_WEATHER_DUPLICATE_GAME")
    missing = sorted(expected - set(observed))
    extra = sorted(set(observed) - expected)
    if missing or extra:
        raise RuntimeError(
            "CFB_SDV_HISTORICAL_WEATHER_COVERAGE_MISMATCH:"
            f"missing={missing[:20]}:extra={extra[:20]}"
        )
    return (
        rows,
        sorted(receipts, key=lambda r: (r["season"], r["stadium_id"])),
        resolutions,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset-root", type=Path, required=True)
    ap.add_argument("--weather-out", type=Path, required=True)
    ap.add_argument("--weather-receipts-out", type=Path, required=True)
    ap.add_argument("--asset-workers", type=int, default=8)
    ap.add_argument("--weather-workers", type=int, default=8)
    args = ap.parse_args()

    plan = acquisition_plan()
    with ThreadPoolExecutor(max_workers=max(1, int(args.asset_workers))) as pool:
        acquired = list(pool.map(lambda item: _download_asset(item, args.asset_root), plan))
    acquired.sort(key=lambda x: (x[0].season, x[0].dataset))
    validate_receipts(plan, [x[1] for x in acquired])

    schedules: list[dict] = []
    for item, _, parsed in acquired:
        if item.dataset == "cfb_schedules":
            if parsed is None:
                raise SystemExit(f"CFB_SDV_SCHEDULE_PARSE_MISSING:{item.season}")
            schedules.extend(parsed)

    games = _evaluated_games(schedules)
    seasons = {int(g["season"]) for g in games}
    if seasons != set(range(FROZEN_FIRST_ROW_SEASON, FROZEN_END_SEASON + 1)):
        raise SystemExit("CFB_SDV_EVALUATED_GAME_SEASON_COVERAGE_INVALID")

    venue_raw = _get(VENUE_SOURCE_URL)
    if sha256(venue_raw).hexdigest() != VENUE_SOURCE_SHA256:
        raise SystemExit("CFB_SDV_VENUE_SOURCE_HASH_MISMATCH")

    weather, window_receipts, venue_resolutions = _historical_weather(
        games=games,
        venue_raw=venue_raw,
        workers=args.weather_workers,
    )

    args.weather_out.parent.mkdir(parents=True, exist_ok=True)
    args.weather_receipts_out.parent.mkdir(parents=True, exist_ok=True)
    args.weather_out.write_text(
        json.dumps(weather, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.weather_receipts_out.write_text(
        json.dumps({
            "schema": "CFB_SDV_HISTORICAL_WEATHER_RECEIPTS_V2",
            "source_id": WEATHER_SOURCE_ID,
            "venue_source": {
                "repository": VENUE_SOURCE_REPOSITORY,
                "commit_sha": VENUE_SOURCE_COMMIT,
                "path": VENUE_SOURCE_PATH,
                "git_blob_sha1": VENUE_SOURCE_GIT_BLOB_SHA1,
                "content_sha256": VENUE_SOURCE_SHA256,
                "byte_count": len(venue_raw),
            },
            "outdoor_windows": window_receipts,
            "venue_resolution_counts": venue_resolutions,
            "normalized_row_count": len(weather),
            "normalized_rows_sha256": sha256(
                json.dumps(
                    weather,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            "governance": {
                "attempts_consumed": 0,
                "evaluation_performed": False,
                "model_p_created": False,
                "promotion_authority": False,
                "official_authority": False,
            },
        }, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": "ACQUIRED_NO_EVALUATION",
        "asset_count": len(acquired),
        "weather_row_count": len(weather),
        "weather_source": WEATHER_SOURCE_ID,
        "venue_source_sha256": VENUE_SOURCE_SHA256,
        "attempts_consumed": 0,
        "evaluation_performed": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
