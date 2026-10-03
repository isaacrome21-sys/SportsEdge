#!/usr/bin/env python3
"""Materialize the frozen public SportsDataverse CFB selection/training rows.

This is pre-evaluation plumbing only. It performs no candidate fit, no candidate
ranking, consumes zero attempts, creates no Model_P, and grants no promotion,
staking, Truth Gate, evidence-clock, or OFFICIAL authority.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.cfb.sportsdataverse_acquisition import acquisition_plan
from sportsedge.sports.cfb.sportsdataverse_candidate_model import FAMILIES, feature_vector
from sportsedge.sports.cfb.sportsdataverse_csv import parse_csv
from sportsedge.sports.cfb.sportsdataverse_history import (
    _pos_team_id,
    build_prior_season_fallback_snapshots,
    build_season_week_snapshots,
    regular_fbs_schedule_rows,
    validate_dataset,
)
from sportsedge.sports.cfb.sportsdataverse_materializer import (
    SDVMaterializationError,
    materialize_native_candidate_inputs,
)
from sportsedge.sports.cfb.sportsdataverse_prereg_hash import CODE_PATHS, CONFIG_PATHS, verify
from sportsedge.sports.cfb.sportsdataverse_receipts import receipt, validate_receipts
from sportsedge.sports.cfb.sportsdataverse_training_rows import attach_training_labels
from sportsedge.sports.cfb.sportsdataverse_venue_source import (
    apply_pinned_venue_aliases,
    apply_pinned_venue_supplements,
    parse_pinned_venues,
    venue_source_attestation,
)
from sportsedge.sports.cfb.sportsdataverse_weather import (
    bind_historical_weather,
    require_complete_weather,
)
from sportsedge.sports.cfb.sportsdataverse_weather_receipts import bind_weather_rows
from sportsedge.sports.cfb.sportsdataverse_weather_transport import (
    BASE_URL,
    SOURCE_ID,
    batch_request_params,
    map_batch_payload,
    select_kickoff_hour,
)

PREREG = ROOT / "config/cfb_sportsdataverse_candidate_prereg_v1.json"
WEATHER_CONTRACT = ROOT / "config/cfb_sportsdataverse_historical_weather_contract_v1.json"
USER_AGENT = "SportsEdge-CFB-SDV-materializer/1.0"


class SDVTrainingMaterializerError(RuntimeError):
    pass


def _canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")


def _canonical_sha(value: Any) -> str:
    return sha256(_canonical_bytes(value)).hexdigest()


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _truth(value: object, name: str) -> bool:
    if type(value) is bool:
        return value
    token = str(value or "").strip().lower()
    if token in {"true", "1", "t"}:
        return True
    if token in {"false", "0", "f"}:
        return False
    raise SDVTrainingMaterializerError(f"CFB_SDV_BOOL_INVALID:{name}:{token}")


def _utc(value: object, name: str) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise SDVTrainingMaterializerError(f"CFB_SDV_TIMESTAMP_INVALID:{name}") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise SDVTrainingMaterializerError(f"CFB_SDV_TIMESTAMP_TZ_REQUIRED:{name}")
    return dt.astimezone(timezone.utc)


def _fetch_bytes(url: str, *, cache_path: Path | None = None, attempts: int = 5) -> bytes:
    if cache_path is not None and cache_path.is_file():
        raw = cache_path.read_bytes()
        if raw:
            return raw
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
            with urlopen(req, timeout=120) as response:  # noqa: S310 - frozen HTTPS sources only
                raw = response.read()
            if not raw:
                raise SDVTrainingMaterializerError(f"CFB_SDV_HTTP_EMPTY:{url}")
            if cache_path is not None:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_bytes(raw)
            return raw
        except Exception as exc:  # network errors are retried, then fail closed
            last = exc
            if attempt < attempts:
                time.sleep(min(20, 2 ** (attempt - 1)))
    raise SDVTrainingMaterializerError(f"CFB_SDV_HTTP_FAILED:{url}:{type(last).__name__}") from last


def _verify_prereg() -> tuple[dict[str, Any], dict[str, Any]]:
    prereg = _load(PREREG)
    weather_contract = _load(WEATHER_CONTRACT)
    binding = prereg.get("hash_binding") or {}
    files = {
        path: (ROOT / path).read_text(encoding="utf-8")
        for path in (*CODE_PATHS, *CONFIG_PATHS)
    }
    verify(
        str(binding.get("code_manifest_sha256") or ""),
        str(binding.get("config_bundle_sha256") or ""),
        files,
    )
    gov = prereg.get("governance") or {}
    if gov.get("attempts_consumed") != 0 or gov.get("evaluation_performed") is not False:
        raise SDVTrainingMaterializerError("CFB_SDV_ATTEMPT_BUDGET_NOT_FRESH")
    return prereg, weather_contract


def _acquire_sdv(cache_root: Path) -> tuple[dict[str, list[dict[str, str]]], list[dict[str, Any]], list[dict[str, Any]]]:
    plan = acquisition_plan()
    datasets: dict[str, list[dict[str, str]]] = defaultdict(list)
    receipts = []
    parsed_receipts = []
    for item in plan:
        raw = _fetch_bytes(
            item.url,
            cache_path=cache_root / "sportsdataverse" / item.tag / item.filename,
        )
        raw_receipt = receipt(item, raw)
        rows, parsed = parse_csv(
            raw,
            dataset=item.dataset,
            season=item.season,
            source_url=item.url,
            raw_csv_sha256=raw_receipt.sha256,
        )
        datasets[item.dataset].extend(rows)
        receipts.append(raw_receipt)
        parsed_receipts.append(parsed)
    validate_receipts(plan, receipts)
    return (
        dict(datasets),
        [x.to_dict() for x in receipts],
        [x.to_dict() for x in parsed_receipts],
    )


def _completed_regular_fbs_games(schedule_rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in regular_fbs_schedule_rows(schedule_rows):
        season = int(row["season"])
        if not 2015 <= season <= 2025:
            raise SDVTrainingMaterializerError("CFB_SDV_SCHEDULE_SEASON_OUTSIDE_FROZEN_WINDOW")
        if not _truth(row.get("completed"), f"completed:{row.get('game_id')}"):
            continue
        hp, ap = str(row.get("home_points") or "").strip(), str(row.get("away_points") or "").strip()
        if not hp or not ap:
            raise SDVTrainingMaterializerError(
                f"CFB_SDV_COMPLETED_SCORE_MISSING:{row.get('game_id')}"
            )
        try:
            int(float(hp)); int(float(ap))
        except ValueError as exc:
            raise SDVTrainingMaterializerError(
                f"CFB_SDV_COMPLETED_SCORE_INVALID:{row.get('game_id')}"
            ) from exc
        out.append(dict(row))
    return sorted(out, key=lambda r: (int(r["season"]), int(r["week"]), int(r["game_id"])))


def _scope_complete_advanced_join_games(
    datasets: Mapping[str, list[dict[str, str]]],
) -> tuple[dict[str, list[dict[str, str]]], list[dict[str, Any]]]:
    required = (
        "espn_cfb_adv_team",
        "espn_cfb_adv_situational",
        "espn_cfb_adv_drives",
    )
    validated = {
        dataset: [dict(row) for row in validate_dataset(dataset, datasets[dataset])]
        for dataset in required
    }
    schedule_index: dict[int, tuple[int, int]] = {}
    for row in validate_dataset("cfb_schedules", datasets["cfb_schedules"]):
        game_id = int(row["game_id"])
        stamp = (int(row["season"]), int(row["week"]))
        prior = schedule_index.get(game_id)
        if prior is not None and prior != stamp:
            raise SDVTrainingMaterializerError(
                f"CFB_SDV_ADVANCED_JOIN_SCHEDULE_TIME_AMBIGUOUS:{game_id}"
            )
        schedule_index[game_id] = stamp

    identities_by_dataset: dict[str, dict[int, set[tuple[int, int, int]]]] = {}
    all_game_ids: set[int] = set()
    for dataset, rows in validated.items():
        by_game: dict[int, set[tuple[int, int, int]]] = defaultdict(set)
        for row in rows:
            game_id = int(row["game_id"])
            if game_id not in schedule_index:
                raise SDVTrainingMaterializerError(
                    f"CFB_SDV_ADVANCED_JOIN_SCHEDULE_ID_MISSING:{game_id}"
                )
            schedule_season, schedule_week = schedule_index[game_id]
            if dataset == "espn_cfb_adv_drives":
                season, week = schedule_season, schedule_week
            else:
                season, week = int(row["season"]), int(row["week"])
            by_game[game_id].add((_pos_team_id(row), season, week))
            all_game_ids.add(game_id)
        identities_by_dataset[dataset] = by_game

    keep: set[int] = set()
    exclusions: list[dict[str, Any]] = []
    for game_id in sorted(all_game_ids):
        identities = {
            dataset: [list(value) for value in sorted(identities_by_dataset[dataset].get(game_id, set()))]
            for dataset in required
        }
        identity_sets = [tuple(tuple(value) for value in identities[dataset]) for dataset in required]
        if len(identity_sets[0]) == 2 and all(value == identity_sets[0] for value in identity_sets[1:]):
            keep.add(game_id)
            continue
        exclusions.append({
            "game_id": str(game_id),
            "reason": "CFB_SDV_INCOMPLETE_OR_TEMPORALLY_INCONSISTENT_ADVANCED_JOIN",
            "row_identity_by_dataset": identities,
            "schedule_season_week": list(schedule_index[game_id]),
        })

    scoped = {name: list(rows) for name, rows in datasets.items()}
    for dataset in required:
        scoped[dataset] = [
            row for row in validated[dataset]
            if int(row["game_id"]) in keep
        ]
    return scoped, exclusions


def _snapshots(datasets: Mapping[str, list[dict[str, str]]]):
    schedule = datasets["cfb_schedules"]
    kwargs = dict(
        adv_team_rows=datasets["espn_cfb_adv_team"],
        adv_situational_rows=datasets["espn_cfb_adv_situational"],
        adv_drive_rows=datasets["espn_cfb_adv_drives"],
        schedule_rows=schedule,
    )
    current = []
    for season in range(2015, 2026):
        current.extend(build_season_week_snapshots(**kwargs, season=season))
    prior = []
    for target_season in range(2016, 2026):
        prior.extend(build_prior_season_fallback_snapshots(**kwargs, target_season=target_season))
    return current, prior


def _predictive_surface(
    *,
    games: list[dict[str, Any]],
    current_snapshots,
    prior_snapshots,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    allowed_missing = (
        "CFB_SDV_PREGAME_SNAPSHOT_MISSING:",
        "CFB_SDV_PRIOR_SEASON_SNAPSHOT_REQUIRED:",
        "CFB_SDV_PRIOR_SEASON_SNAPSHOT_REQUIRED_WEEK2:",
    )
    for game in games:
        season = int(game["season"])
        if season == 2015:
            exclusions.append({
                "game_id": str(game["game_id"]),
                "season": season,
                "week": int(game["week"]),
                "reason": "CFB_SDV_2015_SUPPORT_ONLY_NO_2014_PRIOR",
            })
            continue
        if not 2016 <= season <= 2025:
            raise SDVTrainingMaterializerError("CFB_SDV_EVALUATION_SEASON_OUTSIDE_FROZEN_WINDOW")
        try:
            material = materialize_native_candidate_inputs(
                games=[game],
                snapshots=current_snapshots,
                prior_season_snapshots=prior_snapshots,
            )
        except SDVMaterializationError as exc:
            reason = str(exc)
            if reason.startswith(allowed_missing):
                exclusions.append({
                    "game_id": str(game["game_id"]),
                    "season": season,
                    "week": int(game["week"]),
                    "reason": reason.split(":", 1)[0],
                })
                continue
            raise
        if len(material) != 1:
            raise SDVTrainingMaterializerError(
                f"CFB_SDV_MATERIALIZED_ROW_COUNT_INVALID:{game.get('game_id')}:{len(material)}"
            )
        rows.append(material[0])
    return rows, exclusions


def _venue_source(weather_contract: Mapping[str, Any], cache_root: Path):
    cfg = weather_contract.get("venue_coordinate_source") or {}
    repo = str(cfg.get("repository") or "")
    commit = str(cfg.get("commit_sha") or "")
    path = str(cfg.get("path") or "")
    if not repo or not commit or not path:
        raise SDVTrainingMaterializerError("CFB_SDV_VENUE_SOURCE_CONTRACT_INCOMPLETE")
    url = f"https://raw.githubusercontent.com/{repo}/{commit}/{path}"
    raw = _fetch_bytes(url, cache_path=cache_root / "venue" / "venues.csv")
    venues = parse_pinned_venues(
        raw,
        expected_sha256=str(cfg.get("content_sha256") or ""),
        expected_git_blob_sha1=str(cfg.get("git_blob_sha1") or ""),
        expected_row_count=int(cfg.get("row_count") or 0),
    )
    pinned_usable_rows=len(venues)
    supplements=cfg.get("supplements") or []
    venues=apply_pinned_venue_supplements(venues,supplements)
    aliases=cfg.get("aliases") or []
    venues=apply_pinned_venue_aliases(venues,aliases)
    return venues, {
        **venue_source_attestation(raw, usable_rows=pinned_usable_rows),
        "repository": repo,
        "commit_sha": commit,
        "path": path,
        "url": url,
        "supplements": supplements,
        "supplement_count": len(supplements),
        "aliases": aliases,
        "alias_count": len(aliases),
        "combined_usable_rows": len(venues),
    }


def _weather_request(params: Mapping[str, Any], cache_root: Path) -> tuple[Any, dict[str, Any]]:
    query = urlencode({str(k): v for k, v in params.items()})
    url = f"{BASE_URL}?{query}"
    cache_key = sha256(url.encode("utf-8")).hexdigest()
    raw = _fetch_bytes(url, cache_path=cache_root / "weather" / f"{cache_key}.json")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise SDVTrainingMaterializerError("CFB_SDV_WEATHER_JSON_INVALID") from exc
    return payload, {
        "request_sha256": cache_key,
        "params": dict(params),
        "response_sha256": sha256(raw).hexdigest(),
        "response_byte_count": len(raw),
    }


def _unresolved_venue_bindings(
    *,
    predictive_rows: list[dict[str, Any]],
    schedule_by_game: Mapping[str, Mapping[str, Any]],
    venues: Mapping[int, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    unresolved=[]
    for row in predictive_rows:
        gid=str(row["game_id"])
        schedule=schedule_by_game.get(gid)
        if not isinstance(schedule, Mapping):
            raise SDVTrainingMaterializerError(f"CFB_SDV_SCHEDULE_BINDING_MISSING:{gid}")
        raw=str(schedule.get("venue_id") or "").strip()
        try:
            venue_id=int(raw)
        except ValueError as exc:
            raise SDVTrainingMaterializerError(f"CFB_SDV_VENUE_ID_REQUIRED:{gid}") from exc
        if not isinstance(venues.get(venue_id), Mapping):
            unresolved.append({
                "game_id":gid,
                "venue_id":venue_id,
                "venue_name":str(schedule.get("venue") or "").strip() or None,
            })
    return sorted(unresolved,key=lambda row:(int(row["venue_id"]),str(row["game_id"])))


def _attach_weather(
    *,
    predictive_rows: list[dict[str, Any]],
    schedule_by_game: Mapping[str, Mapping[str, Any]],
    venues: Mapping[int, Mapping[str, Any]],
    weather_contract: Mapping[str, Any],
    cache_root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    batch_cfg = ((weather_contract.get("provider") or {}).get("batch_transport") or {})
    max_locations = int(batch_cfg.get("max_locations_per_request") or 50)
    if batch_cfg.get("multiple_coordinates_allowed") is not True or batch_cfg.get("response_mapping") != "REQUEST_ORDER":
        raise SDVTrainingMaterializerError("CFB_SDV_WEATHER_BATCH_CONTRACT_INVALID")

    unresolved=_unresolved_venue_bindings(
        predictive_rows=predictive_rows,
        schedule_by_game=schedule_by_game,
        venues=venues,
    )
    if unresolved:
        raise SDVTrainingMaterializerError(
            "CFB_SDV_REFERENCED_VENUES_UNRESOLVED:"
            + _canonical_sha(unresolved)
            + ":"
            + json.dumps(unresolved[:50],sort_keys=True,separators=(",",":"))
        )

    row_context: dict[str, dict[str, Any]] = {}
    outdoor_by_season: dict[int, set[int]] = defaultdict(set)
    season_dates: dict[int, list[datetime]] = defaultdict(list)
    weather_by_game: dict[str, dict[str, Any]] = {}

    for row in predictive_rows:
        gid = str(row["game_id"])
        schedule = schedule_by_game.get(gid)
        if not isinstance(schedule, Mapping):
            raise SDVTrainingMaterializerError(f"CFB_SDV_SCHEDULE_BINDING_MISSING:{gid}")
        try:
            venue_id = int(str(schedule.get("venue_id") or "").strip())
        except ValueError as exc:
            raise SDVTrainingMaterializerError(f"CFB_SDV_VENUE_ID_REQUIRED:{gid}") from exc
        venue = venues.get(venue_id)
        if not isinstance(venue, Mapping):
            raise SDVTrainingMaterializerError(f"CFB_SDV_REFERENCED_VENUE_UNRESOLVED:{gid}:{venue_id}")
        kickoff = _utc(schedule.get("start_date"), f"start_date:{gid}")
        season = int(row["season"])
        row_context[gid] = {"venue_id": venue_id, "kickoff": kickoff, "season": season}
        if venue["game_indoor"] is True:
            weather_by_game[gid] = {
                "game_id": int(gid),
                "game_indoor": True,
                "wind_speed": None,
                "temperature": None,
            }
        else:
            outdoor_by_season[season].add(venue_id)
            season_dates[season].append(kickoff)

    transport_evidence: list[dict[str, Any]] = []
    for season in sorted(outdoor_by_season):
        venue_ids = sorted(outdoor_by_season[season])
        dates = season_dates[season]
        start_date = min(dates).date().isoformat()
        end_date = (max(dates).date() + timedelta(days=1)).isoformat()
        for offset in range(0, len(venue_ids), max_locations):
            batch_ids = venue_ids[offset:offset + max_locations]
            locations = [venues[venue_id] for venue_id in batch_ids]
            params = batch_request_params(
                locations=locations,
                start_date=start_date,
                end_date=end_date,
                max_locations=max_locations,
            )
            payload, evidence = _weather_request(params, cache_root)
            mapped = map_batch_payload(payload, locations=locations)
            evidence["season"] = season
            evidence["venue_ids"] = batch_ids
            transport_evidence.append(evidence)

            for gid, context in row_context.items():
                if context["season"] != season or context["venue_id"] not in mapped or gid in weather_by_game:
                    continue
                weather_by_game[gid] = select_kickoff_hour(
                    mapped[context["venue_id"]],
                    game_id=int(gid),
                    kickoff_utc=context["kickoff"].isoformat(),
                    game_indoor=False,
                )

    bound = []
    weather_rows = []
    for row in predictive_rows:
        gid = str(row["game_id"])
        weather = weather_by_game.get(gid)
        if weather is None:
            raise SDVTrainingMaterializerError(f"CFB_SDV_HISTORICAL_WEATHER_UNRESOLVED:{gid}")
        bound_row = bind_historical_weather(row, weather)
        bound.append(bound_row)
        weather_rows.append(dict(weather))
    require_complete_weather(bound)

    weather_rows = sorted(weather_rows, key=lambda r: int(r["game_id"]))
    transport_evidence = sorted(
        transport_evidence,
        key=lambda r: (int(r["season"]), tuple(int(x) for x in r["venue_ids"])),
    )
    evidence_bytes = _canonical_bytes(transport_evidence)
    weather_receipt = bind_weather_rows(
        evidence_bytes,
        weather_rows,
        source_id=SOURCE_ID,
    ).to_dict()
    return bound, weather_rows, {
        "transport_requests": transport_evidence,
        "transport_manifest_sha256": sha256(evidence_bytes).hexdigest(),
        "weather_receipt": weather_receipt,
    }


def build_training_bundle(*, cache_root: Path) -> dict[str, Any]:
    prereg, weather_contract = _verify_prereg()
    datasets, raw_receipts, parsed_receipts = _acquire_sdv(cache_root)
    games = _completed_regular_fbs_games(datasets["cfb_schedules"])
    scoped_datasets, advanced_join_exclusions = _scope_complete_advanced_join_games(datasets)
    current, prior = _snapshots(scoped_datasets)
    predictive, exclusions = _predictive_surface(
        games=games,
        current_snapshots=current,
        prior_snapshots=prior,
    )
    if not predictive:
        raise SDVTrainingMaterializerError("CFB_SDV_COMMON_SCOREABLE_SURFACE_EMPTY")

    schedule_by_game = {str(row["game_id"]): row for row in games}
    venues, venue_attestation = _venue_source(weather_contract, cache_root)
    weather_bound, weather_rows, weather_attestation = _attach_weather(
        predictive_rows=predictive,
        schedule_by_game=schedule_by_game,
        venues=venues,
        weather_contract=weather_contract,
        cache_root=cache_root,
    )
    labels = []
    for row in weather_bound:
        source = dict(schedule_by_game[str(row["game_id"])])
        source["home_points"] = int(float(source["home_points"]))
        source["away_points"] = int(float(source["away_points"]))
        labels.append(source)
    training_rows = attach_training_labels(
        predictive_rows=weather_bound,
        completed_games=labels,
    )

    # Prove every emitted row can enter every frozen family before any evaluation.
    family_constants = prereg["candidates"]
    for row in training_rows:
        for family in FAMILIES:
            constants = dict((family_constants.get(family) or {}).get("constants") or {})
            feature_vector(family, row, constants)

    training_rows = sorted(
        training_rows,
        key=lambda r: (int(r["season"]), int(r["week"]), int(r["game_id"])),
    )
    exclusions = sorted(
        exclusions,
        key=lambda r: (int(r["season"]), int(r["week"]), str(r["game_id"]), str(r["reason"])),
    )
    reason_counts = dict(sorted(Counter(row["reason"] for row in exclusions).items()))

    manifest_core = {
        "schema": "CFB_SPORTSDATAVERSE_TRAINING_BUNDLE_V1",
        "status": "MATERIALIZED_ZERO_AUTHORITY",
        "source_contract_identity": prereg["source_contract_identity"],
        "acquisition_window": [2015, 2025],
        "evaluation_row_window": [2016, 2025],
        "training_rows": len(training_rows),
        "training_rows_sha256": _canonical_sha(training_rows),
        "exclusions": len(exclusions),
        "exclusions_sha256": _canonical_sha(exclusions),
        "exclusion_reason_counts": reason_counts,
        "historical_weather_rows": len(weather_rows),
        "historical_weather_rows_sha256": _canonical_sha(weather_rows),
        "raw_asset_receipts_sha256": _canonical_sha(raw_receipts),
        "parsed_asset_receipts_sha256": _canonical_sha(parsed_receipts),
        "advanced_join_exclusions": len(advanced_join_exclusions),
        "advanced_join_exclusions_sha256": _canonical_sha(advanced_join_exclusions),
        "advanced_join_policy": "REQUIRE_IDENTICAL_TWO_TEAM_SEASON_WEEK_IDENTITY_ACROSS_TEAM_SITUATIONAL_DRIVE_DATASETS_USING_SCHEDULE_TIME_FOR_DRIVES",
        "venue_source": venue_attestation,
        "weather": weather_attestation,
        "prereg_hash_binding": dict(prereg["hash_binding"]),
        "authority": {
            "attempt_consumed": False,
            "evaluation_performed": False,
            "model_p_created": False,
            "truth_gate": False,
            "promotion": False,
            "staking": False,
            "evidence_clock": False,
            "official": False,
            "historical_pit": False,
            "backfill": False,
        },
    }
    manifest = {**manifest_core, "manifest_sha256": _canonical_sha(manifest_core)}
    return {
        "training_rows": training_rows,
        "exclusions": exclusions,
        "historical_weather": weather_rows,
        "raw_asset_receipts": raw_receipts,
        "parsed_asset_receipts": parsed_receipts,
        "advanced_join_exclusions": advanced_join_exclusions,
        "manifest": manifest,
    }


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_bytes(value))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-root", type=Path, default=Path(".cache/cfb-sdv-public"))
    parser.add_argument("--out-dir", type=Path, default=Path("artifacts/cfb/sportsdataverse-selection"))
    args = parser.parse_args(argv)

    bundle = build_training_bundle(cache_root=args.cache_root)
    _write(args.out_dir / "training_rows.json", bundle["training_rows"])
    _write(args.out_dir / "exclusions.json", bundle["exclusions"])
    _write(args.out_dir / "historical_weather.json", bundle["historical_weather"])
    _write(args.out_dir / "raw_asset_receipts.json", bundle["raw_asset_receipts"])
    _write(args.out_dir / "parsed_asset_receipts.json", bundle["parsed_asset_receipts"])
    _write(args.out_dir / "advanced_join_exclusions.json", bundle["advanced_join_exclusions"])
    _write(args.out_dir / "training_manifest.json", bundle["manifest"])

    print(json.dumps({
        "status": bundle["manifest"]["status"],
        "training_rows": bundle["manifest"]["training_rows"],
        "training_rows_sha256": bundle["manifest"]["training_rows_sha256"],
        "exclusions": bundle["manifest"]["exclusions"],
        "attempts_consumed": 0,
        "evaluation_performed": False,
        "model_p_created": False,
        "promotion_authority": False,
        "official_authority": False,
        "out_dir": str(args.out_dir),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
