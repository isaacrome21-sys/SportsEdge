#!/usr/bin/env python3
"""Capture first-write prospective raw NFL attempt-9 margin/total forecasts.

This producer consumes only a successfully reconstructed frozen attempt-9 runtime
artifact plus an exact current nflverse schedule snapshot. It creates no Model_P,
edge, stake, Truth-Gate result, promotion state, or OFFICIAL authority.
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

NFLVERSE_SCHEDULE_TIME_ZONE = ZoneInfo("America/New_York")
ARTIFACT_STATUS = "RECONSTRUCTED_FROZEN_OWNER_RUNTIME_NOT_MODEL_P"
SCHEMA = "SPORTSEDGE_NFL_ATTEMPT9_PROSPECTIVE_RAW_PREDICTION_V1"


def _canonical_sha(value: dict[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(raw).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_MAPPING_REQUIRED:{path}")
    return value


def _verify_artifact(artifact: dict[str, Any]) -> str:
    if artifact.get("schema_version") != "SPORTSEDGE_NFL_ATTEMPT9_RUNTIME_ARTIFACT_V1":
        raise ValueError("NFL_ATTEMPT9_RUNTIME_ARTIFACT_SCHEMA_INVALID")
    if artifact.get("status") != ARTIFACT_STATUS:
        raise ValueError("NFL_ATTEMPT9_RUNTIME_ARTIFACT_STATUS_INVALID")
    candidate = artifact.get("candidate")
    if not isinstance(candidate, dict) or candidate.get("selected_attempt") != 9:
        raise ValueError("NFL_ATTEMPT9_RUNTIME_CANDIDATE_INVALID")
    authority = artifact.get("authority")
    if not isinstance(authority, dict):
        raise ValueError("NFL_ATTEMPT9_RUNTIME_AUTHORITY_MISSING")
    for key in (
        "creates_model_p",
        "promotion_authority",
        "truth_gate_pass",
        "official_authority",
        "staking_authority",
        "market_prices_used_as_features",
    ):
        if authority.get(key) is not False:
            raise ValueError(f"NFL_ATTEMPT9_RUNTIME_AUTHORITY_INVALID:{key}")
    expected = str(artifact.get("artifact_sha256") or "").lower()
    if len(expected) != 64:
        raise ValueError("NFL_ATTEMPT9_RUNTIME_ARTIFACT_SHA_MISSING")
    payload = dict(artifact)
    payload.pop("artifact_sha256", None)
    actual = _canonical_sha(payload)
    if actual != expected:
        raise ValueError(f"NFL_ATTEMPT9_RUNTIME_ARTIFACT_SHA_MISMATCH:{actual}:{expected}")
    runtime = artifact.get("runtime")
    if not isinstance(runtime, dict) or not isinstance(runtime.get("targets"), dict):
        raise ValueError("NFL_ATTEMPT9_RUNTIME_TARGETS_MISSING")
    for target in ("margin", "total"):
        row = runtime["targets"].get(target)
        if not isinstance(row, dict):
            raise ValueError(f"NFL_ATTEMPT9_RUNTIME_TARGET_MISSING:{target}")
        for field in ("feature_mean", "feature_std", "coefficients", "intercept"):
            if field not in row:
                raise ValueError(f"NFL_ATTEMPT9_RUNTIME_TARGET_FIELD_MISSING:{target}:{field}")
    return expected


def _kickoff(row: dict[str, str]) -> datetime:
    gameday = str(row.get("gameday") or "").strip()
    gametime = str(row.get("gametime") or "").strip()
    if not gameday or not gametime:
        raise ValueError(f"NFL_ATTEMPT9_SCHEDULE_TIME_MISSING:{row.get('game_id')}")
    try:
        local = datetime.fromisoformat(f"{gameday}T{gametime}:00").replace(
            tzinfo=NFLVERSE_SCHEDULE_TIME_ZONE
        )
    except ValueError as exc:
        raise ValueError(f"NFL_ATTEMPT9_SCHEDULE_TIME_INVALID:{row.get('game_id')}") from exc
    return local.astimezone(timezone.utc)


def _score(value: str | None) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        numeric = float(text)
    except ValueError:
        return None
    if numeric < 0 or numeric != int(numeric):
        return None
    return int(numeric)


def _weighted(values: list[tuple[int, int]], decay: float) -> np.ndarray:
    array = np.asarray(values[-10:], dtype=float)
    weights = float(decay) ** np.arange(len(array) - 1, -1, -1)
    return np.average(array, axis=0, weights=weights)


def _schedule_state(
    schedule: Path,
    *,
    captured: datetime,
    horizon_days: int,
) -> tuple[dict[str, list[tuple[int, int]]], list[dict[str, Any]]]:
    history: defaultdict[str, list[tuple[int, int]]] = defaultdict(list)
    future: list[dict[str, Any]] = []
    horizon = captured + timedelta(days=horizon_days)
    rows: list[tuple[datetime, str, dict[str, str]]] = []
    with schedule.open(newline="", encoding="utf-8") as fh:
        for raw in csv.DictReader(fh):
            if str(raw.get("game_type") or "").upper() not in {"REG", "POST"}:
                continue
            game_id = str(raw.get("game_id") or "").strip()
            home = str(raw.get("home_team") or "").strip()
            away = str(raw.get("away_team") or "").strip()
            if not game_id or not home or not away:
                continue
            try:
                kickoff = _kickoff(raw)
            except ValueError:
                continue
            rows.append((kickoff, game_id, raw))
    rows.sort(key=lambda item: (item[0], item[1]))

    for kickoff, game_id, raw in rows:
        home = str(raw["home_team"]).strip()
        away = str(raw["away_team"]).strip()
        hs = _score(raw.get("home_score"))
        aways = _score(raw.get("away_score"))
        if kickoff < captured and hs is not None and aways is not None:
            history[home].append((hs, aways))
            history[away].append((aways, hs))
            continue
        if not (captured < kickoff <= horizon):
            continue
        try:
            season = int(str(raw.get("season") or "0"))
            week = int(str(raw.get("week") or "0"))
        except ValueError:
            continue
        if season != 2026:
            continue
        future.append(
            {
                "game_id": game_id,
                "season": season,
                "week": week,
                "kickoff_utc": kickoff.isoformat(),
                "home_team": home,
                "away_team": away,
            }
        )
    return dict(history), future


def _features(
    history: dict[str, list[tuple[int, int]]],
    *,
    home: str,
    away: str,
    decay: float,
) -> list[float]:
    home_history = history.get(home) or []
    away_history = history.get(away) or []
    if len(home_history) < 5 or len(away_history) < 5:
        raise ValueError(
            f"NFL_ATTEMPT9_PROSPECTIVE_HISTORY_INSUFFICIENT:{home}:{len(home_history)}:{away}:{len(away_history)}"
        )
    hp = _weighted(home_history, decay)
    ap = _weighted(away_history, decay)
    return [
        float(hp[0]),
        float(hp[1]),
        float(ap[0]),
        float(ap[1]),
        float(hp[0] - hp[1]),
        float(ap[0] - ap[1]),
    ]


def _predict(target: dict[str, Any], features: list[float]) -> float:
    vector = np.asarray(features, dtype=float)
    mean = np.asarray(target["feature_mean"], dtype=float)
    std = np.asarray(target["feature_std"], dtype=float)
    beta = np.asarray(target["coefficients"], dtype=float)
    if vector.shape != (6,) or mean.shape != (6,) or std.shape != (6,) or beta.shape != (6,):
        raise ValueError("NFL_ATTEMPT9_RUNTIME_GEOMETRY_INVALID")
    if np.any(std == 0):
        raise ValueError("NFL_ATTEMPT9_RUNTIME_ZERO_STD")
    scaled = (vector - mean) / std
    return float(scaled @ beta + float(target["intercept"]))


def _validate_existing(existing: dict[str, Any], *, artifact_sha: str, game: dict[str, Any]) -> None:
    if existing.get("schema_version") != SCHEMA:
        raise ValueError("NFL_ATTEMPT9_EXISTING_SCHEMA_MISMATCH")
    expected = {
        "artifact_sha256": artifact_sha,
        "game_id": game["game_id"],
        "season": game["season"],
        "week": game["week"],
        "home_team": game["home_team"],
        "away_team": game["away_team"],
    }
    for key, value in expected.items():
        if existing.get(key) != value:
            raise ValueError(f"NFL_ATTEMPT9_EXISTING_IDENTITY_MISMATCH:{key}")
    for key in ("model_p_created", "promotion_authority", "truth_gate_pass", "official_authority", "staking_authority"):
        if existing.get(key) is not False:
            raise ValueError(f"NFL_ATTEMPT9_EXISTING_AUTHORITY_INVALID:{key}")


def capture(
    *,
    artifact: dict[str, Any],
    schedule: Path,
    output_dir: Path,
    capture_code_git_sha: str,
    captured: datetime,
    horizon_days: int,
) -> dict[str, Any]:
    artifact_sha = _verify_artifact(artifact)
    schedule_raw = schedule.read_bytes()
    schedule_sha = sha256(schedule_raw).hexdigest()
    history, future = _schedule_state(schedule, captured=captured, horizon_days=horizon_days)
    decay = float(artifact["candidate"]["decay"])
    targets = artifact["runtime"]["targets"]
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[dict[str, str]] = []
    skipped: list[str] = []
    blocked: list[dict[str, str]] = []
    for game in future:
        path = output_dir / f"{game['game_id']}.json"
        if path.exists():
            existing = _read_json(path)
            _validate_existing(existing, artifact_sha=artifact_sha, game=game)
            skipped.append(game["game_id"])
            continue
        try:
            features = _features(
                history,
                home=game["home_team"],
                away=game["away_team"],
                decay=decay,
            )
        except ValueError as exc:
            blocked.append({"game_id": game["game_id"], "reason": str(exc)})
            continue
        payload: dict[str, Any] = {
            "schema_version": SCHEMA,
            "candidate_id": "nfl_attempt9_exponential_recency_weighted_baseline",
            "selected_attempt": 9,
            "artifact_sha256": artifact_sha,
            "schedule_snapshot_sha256": schedule_sha,
            "capture_code_git_sha": str(capture_code_git_sha),
            "captured_at_utc": captured.isoformat(),
            **game,
            "feature_names": list(artifact["candidate"]["feature_names"]),
            "feature_values": features,
            "raw_predicted_home_margin": _predict(targets["margin"], features),
            "raw_predicted_game_total": _predict(targets["total"], features),
            "market_price_used": False,
            "model_p_created": False,
            "promotion_authority": False,
            "truth_gate_pass": False,
            "official_authority": False,
            "staking_authority": False,
        }
        payload["prediction_sha256"] = _canonical_sha(payload)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append({"game_id": game["game_id"], "prediction_sha256": payload["prediction_sha256"]})
    return {
        "status": "PROSPECTIVE_RAW_PREDICTIONS_CAPTURED" if written else "NO_NEW_ELIGIBLE_GAMES",
        "captured_at_utc": captured.isoformat(),
        "artifact_sha256": artifact_sha,
        "schedule_snapshot_sha256": schedule_sha,
        "new_prediction_count": len(written),
        "skipped_existing_count": len(skipped),
        "blocked_game_count": len(blocked),
        "new_predictions": written,
        "skipped_existing_game_ids": skipped,
        "blocked_games": blocked,
        "model_p_created": False,
        "promotion_authority": False,
        "official_authority": False,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact", type=Path, required=True)
    ap.add_argument("--schedule", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--capture-code-git-sha", required=True)
    ap.add_argument("--captured-at-utc")
    ap.add_argument("--horizon-days", type=int, default=9)
    args = ap.parse_args()
    if args.horizon_days < 1 or args.horizon_days > 14:
        raise SystemExit("NFL_ATTEMPT9_PROSPECTIVE_HORIZON_INVALID")
    captured = (
        datetime.fromisoformat(args.captured_at_utc.replace("Z", "+00:00"))
        if args.captured_at_utc
        else datetime.now(timezone.utc)
    )
    if captured.tzinfo is None or captured.utcoffset() is None:
        raise SystemExit("NFL_ATTEMPT9_PROSPECTIVE_CAPTURE_TIME_TZ_REQUIRED")
    captured = captured.astimezone(timezone.utc)
    summary = capture(
        artifact=_read_json(args.artifact),
        schedule=args.schedule,
        output_dir=args.output_dir,
        capture_code_git_sha=args.capture_code_git_sha,
        captured=captured,
        horizon_days=args.horizon_days,
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
