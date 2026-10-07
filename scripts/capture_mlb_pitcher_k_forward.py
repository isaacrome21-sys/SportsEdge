#!/usr/bin/env python3
"""Capture and settle prospective evidence for the frozen MLB pitcher-K candidate."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from typing import Any, Mapping
from zoneinfo import ZoneInfo

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from research_mlb_pitcher_prop_promotion import (
    PITContextArchive,
    PITContextError,
    _match_game,
    _parse_iso,
    bind_pit_context,
    select_units,
)
from sportsedge.mlb_all_market_features import MLBAllMarketHistorySource
from sportsedge.mlb_generic_features import MLBGenericFeatureError
from sportsedge.mlb_history_cache import MLBHistoryCachedOpener
from sportsedge.mlb_pitcher_k_composite_candidate import build_composite_candidate
from sportsedge.mlb_pitcher_k_forward_validation import (
    build_prediction_receipt,
    canonical_sha256,
    settle_prediction,
)
from sportsedge.mlb_pitcher_k_skill_binding import bind_statcast_skill
from sportsedge.mlb_pitcher_k_workload_source import build_from_history_source
from sportsedge.mlb_pitcher_subject import resolve_pitcher_subject
from sportsedge.mlb_source import fetch_boxscore, fetch_schedule, parse_game_start
from sportsedge.mlb_statcast_preview_source import pitcher_context

EASTERN = ZoneInfo("America/New_York")
STATCAST_MAX_AGE_SECONDS = 36 * 3600


class ForwardCaptureBlocked(RuntimeError):
    pass


def _git_paths(prefix: str) -> list[str]:
    try:
        raw = subprocess.check_output(
            ["git", "ls-tree", "-r", "--name-only", "origin/data", prefix],
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise ForwardCaptureBlocked(f"DATA_BRANCH_LIST_FAILED:{prefix}") from exc
    return sorted(path for path in raw.splitlines() if path.strip())


def _git_json(path: str) -> dict[str, Any]:
    try:
        raw = subprocess.check_output(["git", "show", f"origin/data:{path}"])
        value = json.loads(raw)
    except Exception as exc:
        raise ForwardCaptureBlocked(f"DATA_BRANCH_JSON_FAILED:{path}") from exc
    if not isinstance(value, dict):
        raise ForwardCaptureBlocked(f"DATA_BRANCH_NOT_OBJECT:{path}")
    return value


def _latest_prop_snapshot() -> tuple[str, dict[str, Any]]:
    paths = [
        path for path in _git_paths("runtime/mlb-prop-pit")
        if "/props_" in path and path.endswith(".json")
    ]
    if not paths:
        raise ForwardCaptureBlocked("NO_PROP_PIT_SNAPSHOT")
    path = paths[-1]
    payload = _git_json(path)
    if payload.get("archive_type") != "MLB_PROP_PIT_QUOTES":
        raise ForwardCaptureBlocked("LATEST_PROP_SNAPSHOT_SCHEMA_MISMATCH")
    return path, payload


def _parse_manifest_time(value: Mapping[str, Any]) -> datetime | None:
    raw = value.get("retrieved_at")
    if not raw:
        return None
    try:
        return _parse_iso(raw)
    except Exception:
        return None


def _statcast_at_or_before(observed_at: datetime) -> dict[str, Any] | None:
    manifests = [
        path for path in _git_paths("runtime/statcast/runs")
        if path.endswith("/manifest.json")
    ]
    eligible: list[tuple[datetime, str, dict[str, Any]]] = []
    for path in manifests:
        try:
            manifest = _git_json(path)
        except ForwardCaptureBlocked:
            continue
        retrieved = _parse_manifest_time(manifest)
        if (
            retrieved is None
            or retrieved > observed_at
            or manifest.get("status") != "PASS"
            or (observed_at - retrieved).total_seconds() > STATCAST_MAX_AGE_SECONDS
        ):
            continue
        eligible.append((retrieved, path, manifest))
    if not eligible:
        return None
    retrieved, manifest_path, manifest = max(eligible, key=lambda item: (item[0], item[1]))
    root = manifest_path.rsplit("/", 1)[0]
    pitchers_path = root + "/pitchers.json"
    provenance_path = root + "/provenance.json"
    try:
        pitchers_raw = subprocess.check_output(["git", "show", f"origin/data:{pitchers_path}"])
        pitchers = json.loads(pitchers_raw)
        provenance = _git_json(provenance_path)
    except Exception as exc:
        raise ForwardCaptureBlocked("STATCAST_ARCHIVE_BINDING_FAILED") from exc
    if not isinstance(pitchers, list):
        raise ForwardCaptureBlocked("STATCAST_PITCHERS_NOT_LIST")
    if provenance.get("schema") != "SPORTSEDGE_STATCAST_MAIN_PROVENANCE_V1":
        raise ForwardCaptureBlocked("STATCAST_PROVENANCE_SCHEMA_MISMATCH")
    if provenance.get("eligible_for_forward_evaluation") is not True:
        raise ForwardCaptureBlocked("STATCAST_NOT_FORWARD_ELIGIBLE")
    return {
        "retrieved_at": retrieved,
        "manifest_path": manifest_path,
        "pitchers_path": pitchers_path,
        "provenance_path": provenance_path,
        "manifest": manifest,
        "pitchers": pitchers,
        "provenance": provenance,
    }


def _find_pitcher_statcast(snapshot: Mapping[str, Any], pitcher_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
    rows = snapshot.get("pitchers")
    if not isinstance(rows, list):
        raise ForwardCaptureBlocked("STATCAST_PITCHERS_NOT_LIST")
    matches = [
        row for row in rows
        if isinstance(row, Mapping) and str(row.get("entity_id")) == str(int(pitcher_id))
    ]
    if len(matches) != 1:
        raise ForwardCaptureBlocked("STATCAST_PITCHER_IDENTITY_UNRESOLVED")
    context = pitcher_context(matches[0])
    if not isinstance(context, dict):
        raise ForwardCaptureBlocked("STATCAST_PITCHER_CONTEXT_MISSING")
    proof = {
        "retrieved_at": snapshot["retrieved_at"].isoformat(),
        "manifest_path": snapshot["manifest_path"],
        "pitchers_path": snapshot["pitchers_path"],
        "provenance_path": snapshot["provenance_path"],
        "pitcher_row_sha256": canonical_sha256(dict(matches[0])),
        "run_id": str((snapshot.get("provenance") or {}).get("run_id") or ""),
        "head_sha": str((snapshot.get("provenance") or {}).get("head_sha") or ""),
    }
    return context, proof


def _candidate_for_unit(
    *,
    unit: Mapping[str, Any],
    game,
    pitcher_id: int,
    team_id: int,
    context_archive: PITContextArchive,
    statcast_snapshot: Mapping[str, Any],
    cache_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    observed = _parse_iso(unit["observed_at"])
    target_date = (
        datetime.fromisoformat(str(game.official_date)).date()
        if game.official_date
        else parse_game_start(game.game_date).astimezone(EASTERN).date()
    )
    opener = MLBHistoryCachedOpener(target_date=target_date, cache_dir=cache_dir)
    source = MLBAllMarketHistorySource(opener=opener, retrieved_at=observed)

    context = context_archive.latest(game_pk=int(game.game_pk), observed_at=observed)
    context_proof = bind_pit_context(
        source, game_pk=int(game.game_pk), market="PITCHER_K", proof=context
    )

    workload = build_from_history_source(
        source, player_id=int(pitcher_id), target_date=target_date
    )
    if int(workload.get("start_count") or 0) < 5:
        raise ForwardCaptureBlocked("WORKLOAD_LT_5")

    feature = source.feature_row(
        game_pk=int(game.game_pk),
        market="PITCHER_K",
        entity_id=str(int(pitcher_id)),
        target_date=target_date,
        away_team_id=int(game.away_id),
        home_team_id=int(game.home_id),
        player_id=int(pitcher_id),
        team_id=int(team_id),
    )
    features = feature.get("features")
    if not isinstance(features, Mapping):
        raise ForwardCaptureBlocked("PITCHER_K_FEATURES_MISSING")
    raw_adj = features.get("opp_k_adjustment")
    if not isinstance(raw_adj, Mapping):
        raise ForwardCaptureBlocked("OPPONENT_K_ADJUSTMENT_MISSING")
    opp_k = deepcopy(dict(raw_adj))
    lineup_k = opp_k.pop("lineup_k_adjustment", None)
    composite = build_composite_candidate(
        workload=workload,
        opp_k_adjustment=opp_k,
        lineup_k_adjustment=lineup_k,
    )

    statcast_context, statcast_proof = _find_pitcher_statcast(statcast_snapshot, pitcher_id)
    candidate = bind_statcast_skill(
        composite,
        pitcher_context=statcast_context,
        provenance=statcast_snapshot["provenance"],
    )
    return candidate, context_proof, statcast_proof


def _write_create_only(path: Path, payload: Mapping[str, Any]) -> str:
    data = json.dumps(dict(payload), indent=2, sort_keys=True, allow_nan=False) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != data:
            raise ForwardCaptureBlocked(f"CREATE_ONLY_COLLISION:{path}")
        return "EXISTS_IDENTICAL"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")
    return "CREATED"


def _prediction_paths_from_data() -> list[str]:
    return [
        path for path in _git_paths("data/mlb_pitcher_k_forward/predictions")
        if path.endswith(".json")
    ]


def _existing_settlement_ids() -> set[str]:
    out: set[str] = set()
    for path in _git_paths("data/mlb_pitcher_k_forward/settlements"):
        if path.endswith(".json"):
            out.add(Path(path).stem)
    return out


def _settle_existing(*, output_root: Path, now: datetime) -> tuple[int, list[dict[str, Any]]]:
    paths = _prediction_paths_from_data()
    settled_ids = _existing_settlement_ids()
    schedule_cache: dict[str, Any] = {}
    box_cache: dict[int, Any] = {}
    created = 0
    blockers: list[dict[str, Any]] = []
    for path in paths:
        prediction = _git_json(path)
        pred_sha = str(prediction.get("receipt_sha256") or "")
        if len(pred_sha) != 64 or pred_sha in settled_ids:
            continue
        try:
            first_pitch = _parse_iso(prediction["first_pitch_at_utc"])
            day = first_pitch.astimezone(EASTERN).date().isoformat()
            if day not in schedule_cache:
                schedule_cache[day] = fetch_schedule(day, now=now)
            game = next(
                (g for g in schedule_cache[day] if int(g.game_pk) == int(prediction["game_pk"])),
                None,
            )
            if game is None or str(game.status).lower() != "final":
                continue
            game_pk = int(game.game_pk)
            if game_pk not in box_cache:
                box_cache[game_pk] = fetch_boxscore(game_pk)
            box = box_cache[game_pk]
            pid = int(prediction["pitcher_id"])
            player = None
            for side in ("away", "home"):
                team = ((box.get("teams") or {}).get(side) or {})
                found = (team.get("players") or {}).get(f"ID{pid}")
                if isinstance(found, Mapping):
                    player = found
                    break
            if not isinstance(player, Mapping):
                raise ForwardCaptureBlocked("SETTLEMENT_PITCHER_NOT_IN_BOXSCORE")
            pitching = ((player.get("stats") or {}).get("pitching") or {})
            started = int(pitching.get("gamesStarted") or 0) >= 1
            realized = int(pitching.get("strikeOuts") or 0) if started else None
            receipt = settle_prediction(
                prediction,
                realized_strikeouts=realized,
                started=started,
                settled_at=now.isoformat(),
            )
            dest = output_root / "settlements" / day / f"{pred_sha}.json"
            state = _write_create_only(dest, receipt)
            if state == "CREATED":
                created += 1
        except Exception as exc:
            blockers.append({"prediction_path": path, "reason": f"{type(exc).__name__}:{exc}"})
    return created, blockers


def run(*, output_root: Path, cache_dir: Path, now: datetime | None = None) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    prop_path, payload = _latest_prop_snapshot()
    units, selection_drops = select_units([payload])
    units = [unit for unit in units if unit.get("market") == "PITCHER_K"]
    context_archive = PITContextArchive.from_data()
    predictions = 0
    blockers: list[dict[str, Any]] = []
    schedule_cache: dict[str, Any] = {}
    statcast_cache: dict[str, Any] = {}

    for unit in units:
        try:
            observed = _parse_iso(unit["observed_at"])
            first_pitch = _parse_iso(unit["first_pitch_at"])
            if now >= first_pitch:
                raise ForwardCaptureBlocked("CAPTURE_RUN_AT_OR_AFTER_FIRST_PITCH")
            day = first_pitch.astimezone(EASTERN).date().isoformat()
            if day not in schedule_cache:
                schedule_cache[day] = fetch_schedule(day, now=observed)
            game = _match_game(dict(unit), schedule_cache[day])
            if game is None:
                raise ForwardCaptureBlocked("GAME_IDENTITY_UNRESOLVED")
            if str(game.status).lower() != "preview":
                raise ForwardCaptureBlocked(f"GAME_NOT_PREVIEW:{game.status}")
            row = SimpleNamespace(subject_name=unit.get("entity_name"), subject_id=None)
            pitcher_id_text, team_id = resolve_pitcher_subject(row, game)
            pitcher_id = int(pitcher_id_text)

            stat_key = observed.isoformat()
            if stat_key not in statcast_cache:
                statcast_cache[stat_key] = _statcast_at_or_before(observed)
            statcast_snapshot = statcast_cache[stat_key]
            if statcast_snapshot is None:
                raise ForwardCaptureBlocked("NO_ELIGIBLE_PREQUOTE_STATCAST_SNAPSHOT")

            candidate, context_proof, statcast_proof = _candidate_for_unit(
                unit=unit,
                game=game,
                pitcher_id=pitcher_id,
                team_id=int(team_id),
                context_archive=context_archive,
                statcast_snapshot=statcast_snapshot,
                cache_dir=cache_dir,
            )
            receipt = build_prediction_receipt(
                candidate=candidate,
                game_pk=int(game.game_pk),
                pitcher_id=pitcher_id,
                pitcher_team_id=int(team_id),
                line=float(unit["line"]),
                over_odds=int(unit["over_odds"]),
                under_odds=int(unit["under_odds"]),
                observed_at=str(unit["observed_at"]),
                first_pitch_at=str(unit["first_pitch_at"]),
                provider_event_id=str(unit["provider_event_id"]),
                entity_name=str(unit.get("entity_name") or ""),
                quote_archive_path=prop_path,
                context_proof=context_proof,
                statcast_proof=statcast_proof,
            )
            dest = (
                output_root / "predictions" / day /
                f"{receipt['receipt_sha256']}.json"
            )
            state = _write_create_only(dest, receipt)
            if state == "CREATED":
                predictions += 1
        except (PITContextError, MLBGenericFeatureError, Exception) as exc:
            blockers.append({
                "provider_event_id": str(unit.get("provider_event_id") or ""),
                "entity_name": str(unit.get("entity_name") or ""),
                "observed_at": str(unit.get("observed_at") or ""),
                "reason": f"{type(exc).__name__}:{exc}",
            })

    settlements, settlement_blockers = _settle_existing(output_root=output_root, now=now)
    blockers.extend(settlement_blockers)
    run_id = str(os.environ.get("GITHUB_RUN_ID") or now.strftime("%Y%m%dT%H%M%SZ"))
    attempt = str(os.environ.get("GITHUB_RUN_ATTEMPT") or "1")
    summary = {
        "schema": "SPORTSEDGE_MLB_PITCHER_K_FORWARD_RUN_V1",
        "status": "OK",
        "run_id": run_id,
        "run_attempt": attempt,
        "observed_at_utc": now.isoformat(),
        "quote_archive_path": prop_path,
        "eligible_quote_units": len(units),
        "predictions_created": predictions,
        "settlements_created": settlements,
        "selection_drops": selection_drops,
        "blocked_count": len(blockers),
        "blockers": blockers,
        "authority": {
            "forward_validation_evidence_only": True,
            "production_activation": False,
            "promotion": False,
            "official": False,
        },
    }
    summary["summary_sha256"] = canonical_sha256(summary)
    _write_create_only(output_root / "runs" / f"{run_id}_{attempt}.json", summary)
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path("data/mlb_pitcher_k_forward"))
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/mlb-pitcher-k-forward"))
    args = parser.parse_args(argv)
    try:
        result = run(output_root=args.output_root, cache_dir=args.cache_dir)
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "reason": f"{type(exc).__name__}:{exc}"}, sort_keys=True))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
