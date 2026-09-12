#!/usr/bin/env python3
"""Capture first-write prospective V2G research predictions for future NFL games."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.nfl.m2_v2g_forward import (
    build_prospective_prediction,
    validate_prospective_prediction,
)

NFLVERSE_SCHEDULE_TIME_ZONE = ZoneInfo("America/New_York")


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_MAPPING_REQUIRED:{path}")
    return value


def _kickoff(row: dict[str, str]) -> datetime:
    gameday = str(row.get("gameday") or "").strip()
    gametime = str(row.get("gametime") or "").strip()
    if not gameday or not gametime:
        raise ValueError(f"NFL_V2G_FORWARD_SCHEDULE_TIME_MISSING:{row.get('game_id')}")
    try:
        local = datetime.fromisoformat(f"{gameday}T{gametime}:00").replace(tzinfo=NFLVERSE_SCHEDULE_TIME_ZONE)
    except ValueError as exc:
        raise ValueError(f"NFL_V2G_FORWARD_SCHEDULE_TIME_INVALID:{row.get('game_id')}") from exc
    return local.astimezone(timezone.utc)


def _future_games(schedule: Path, *, captured: datetime, horizon_days: int) -> list[dict]:
    horizon = captured + timedelta(days=horizon_days)
    rows: list[dict] = []
    with schedule.open(newline="", encoding="utf-8") as fh:
        for raw in csv.DictReader(fh):
            if str(raw.get("game_type") or "").upper() != "REG":
                continue
            try:
                season = int(str(raw.get("season") or "0"))
                week = int(str(raw.get("week") or "0"))
            except ValueError:
                continue
            if season < 2026:
                continue
            kickoff = _kickoff(raw)
            if not (captured < kickoff <= horizon):
                continue
            game_id = str(raw.get("game_id") or "").strip()
            home = str(raw.get("home_team") or "").strip()
            away = str(raw.get("away_team") or "").strip()
            if not game_id or not home or not away:
                raise ValueError("NFL_V2G_FORWARD_SCHEDULE_IDENTITY_INVALID")
            rows.append({
                "game_id": game_id,
                "season": season,
                "week": week,
                "kickoff_utc": kickoff.isoformat(),
                "home_team": home,
                "away_team": away,
            })
    rows.sort(key=lambda x: (x["kickoff_utc"], x["game_id"]))
    return rows


def _validate_existing_identity(existing: dict, correction: dict, game: dict) -> None:
    """Require an immutable prior row to belong to this exact frozen V2G lane."""
    validate_prospective_prediction(existing)
    bound = correction.get("source_bound_research_artifact")
    if not isinstance(bound, dict):
        raise ValueError("NFL_V2G_FORWARD_FROZEN_ARTIFACT_REQUIRED")
    expected = {
        "candidate_id": str(correction.get("candidate_id") or ""),
        "artifact_sha256": str(bound.get("artifact_sha256") or "").lower(),
        "implementation_commit_sha": str(correction.get("implementation_commit_sha") or "").lower(),
        "candidate_source_git_blob_sha1": str(correction.get("candidate_source_git_blob_sha1") or "").lower(),
        "preregistration_commit_sha": str(correction.get("preregistration_commit_sha") or "").lower(),
        "game_id": str(game["game_id"]),
        "season": int(game["season"]),
        "week": int(game["week"]),
        "home_team": str(game["home_team"]),
        "away_team": str(game["away_team"]),
    }
    for field, wanted in expected.items():
        actual = existing.get(field)
        if isinstance(wanted, str):
            actual = str(actual or "").lower() if field.endswith(("sha256", "sha1", "_sha")) or "commit_sha" in field else str(actual or "")
        elif isinstance(wanted, int):
            try:
                actual = int(actual)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"NFL_V2G_FORWARD_EXISTING_IDENTITY_MISMATCH:{field}") from exc
        if actual != wanted:
            raise ValueError(f"NFL_V2G_FORWARD_EXISTING_IDENTITY_MISMATCH:{field}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact", type=Path, required=True)
    ap.add_argument("--implementation-freeze", type=Path, required=True)
    ap.add_argument("--freeze-correction", type=Path, required=True)
    ap.add_argument("--schedule", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--capture-code-git-sha", required=True)
    ap.add_argument("--captured-at-utc")
    ap.add_argument("--horizon-days", type=int, default=8)
    args = ap.parse_args()

    if args.horizon_days < 1 or args.horizon_days > 14:
        raise SystemExit("NFL_V2G_FORWARD_HORIZON_INVALID")
    captured = (
        datetime.fromisoformat(args.captured_at_utc.replace("Z", "+00:00"))
        if args.captured_at_utc
        else datetime.now(timezone.utc)
    )
    if captured.tzinfo is None or captured.utcoffset() is None:
        raise SystemExit("NFL_V2G_FORWARD_CAPTURE_TIME_TZ_REQUIRED")
    captured = captured.astimezone(timezone.utc)

    artifact = _read_json(args.artifact)
    implementation_freeze = _read_json(args.implementation_freeze)
    correction = _read_json(args.freeze_correction)
    schedule_raw = args.schedule.read_bytes()
    schedule_sha = sha256(schedule_raw).hexdigest()
    games = _future_games(args.schedule, captured=captured, horizon_days=args.horizon_days)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    written: list[dict] = []
    skipped_existing: list[str] = []
    for game in games:
        output = args.output_dir / f"{game['game_id']}.json"
        if output.exists():
            existing = _read_json(output)
            _validate_existing_identity(existing, correction, game)
            skipped_existing.append(game["game_id"])
            continue
        record = build_prospective_prediction(
            artifact=artifact,
            implementation_freeze=implementation_freeze,
            freeze_correction=correction,
            schedule_snapshot_sha256=schedule_sha,
            capture_code_git_sha=args.capture_code_git_sha,
            captured_at_utc=captured.isoformat(),
            **game,
        )
        validate_prospective_prediction(record)
        output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append({"game_id": game["game_id"], "prediction_sha256": record["prediction_sha256"]})

    summary = {
        "status": "PROSPECTIVE_PREDICTIONS_CAPTURED" if written else "NO_NEW_ELIGIBLE_GAMES",
        "captured_at_utc": captured.isoformat(),
        "schedule_snapshot_sha256": schedule_sha,
        "new_prediction_count": len(written),
        "skipped_existing_count": len(skipped_existing),
        "new_predictions": written,
        "skipped_existing_game_ids": skipped_existing,
        "promotion_authority": False,
        "may_create_model_p": False,
        "official_status_granted": False,
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
