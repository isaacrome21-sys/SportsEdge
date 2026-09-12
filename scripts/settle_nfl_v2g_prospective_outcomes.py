#!/usr/bin/env python3
"""Capture objective postgame outcomes for immutable NFL V2G predictions.

This is an evidence-preservation lane only. It never reads sportsbook prices,
never changes the frozen V2G prediction, and has no promotion/Model_P authority.
Existing outcome files are immutable and are never overwritten.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sportsedge.sports.nfl.m2_v2g_forward import (
    canonical_bytes,
    validate_prospective_prediction,
)

OUTCOME_SCHEMA = "NFL_M2_V2G_PROSPECTIVE_OUTCOME_V1"
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class OutcomeError(ValueError):
    pass


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise OutcomeError(code)


def _ts(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise OutcomeError(f"NFL_V2G_OUTCOME_TIMESTAMP_INVALID:{field}") from exc
    _require(parsed.tzinfo is not None and parsed.utcoffset() is not None,
             f"NFL_V2G_OUTCOME_TIMESTAMP_TZ_REQUIRED:{field}")
    return parsed.astimezone(timezone.utc)


def _hex(value: Any, *, bits: int, field: str) -> str:
    text = str(value or "").strip().lower()
    pattern = _SHA256_RE if bits == 256 else _GIT_SHA_RE if bits == 160 else None
    _require(pattern is not None and bool(pattern.fullmatch(text)),
             f"NFL_V2G_OUTCOME_HASH_INVALID:{field}")
    return text


def outcome_sha256(value: Mapping[str, Any]) -> str:
    payload = dict(value)
    payload.pop("outcome_sha256", None)
    return sha256(canonical_bytes(payload)).hexdigest()


def _score(value: Any, field: str) -> int:
    text = str(value or "").strip()
    _require(bool(text), f"NFL_V2G_OUTCOME_SCORE_MISSING:{field}")
    try:
        number = float(text)
    except ValueError as exc:
        raise OutcomeError(f"NFL_V2G_OUTCOME_SCORE_INVALID:{field}") from exc
    integer = int(number)
    _require(number == integer and integer >= 0, f"NFL_V2G_OUTCOME_SCORE_INVALID:{field}")
    return integer


def validate_outcome(record: Mapping[str, Any]) -> str:
    _require(record.get("schema_version") == OUTCOME_SCHEMA, "NFL_V2G_OUTCOME_SCHEMA_INVALID")
    _require(record.get("status") == "PROSPECTIVE_RESEARCH_OUTCOME_CAPTURED", "NFL_V2G_OUTCOME_STATUS_INVALID")
    _require(record.get("outcome_source") == "NFLVERSE_GAMES_CSV_POSTGAME_SCORE",
             "NFL_V2G_OUTCOME_SOURCE_INVALID")
    game_id = str(record.get("game_id") or "").strip()
    home_team = str(record.get("home_team") or "").strip()
    away_team = str(record.get("away_team") or "").strip()
    _require(bool(game_id), "NFL_V2G_OUTCOME_GAME_ID_REQUIRED")
    _require(bool(home_team) and bool(away_team) and home_team != away_team,
             "NFL_V2G_OUTCOME_TEAM_IDENTITY_INVALID")
    try:
        season = int(record.get("season"))
        week = int(record.get("week"))
    except (TypeError, ValueError) as exc:
        raise OutcomeError("NFL_V2G_OUTCOME_GAME_SCOPE_INVALID") from exc
    _require(season >= 2026 and week >= 1, "NFL_V2G_OUTCOME_GAME_SCOPE_INVALID")

    prediction_sha = _hex(record.get("prediction_sha256"), bits=256, field="prediction_sha256")
    del prediction_sha
    _hex(record.get("artifact_sha256"), bits=256, field="artifact_sha256")
    _hex(record.get("result_schedule_snapshot_sha256"), bits=256, field="result_schedule_snapshot_sha256")
    _hex(record.get("prediction_capture_code_git_sha"), bits=160, field="prediction_capture_code_git_sha")
    _hex(record.get("settlement_code_git_sha"), bits=160, field="settlement_code_git_sha")

    kickoff = _ts(record.get("kickoff_utc"), "kickoff_utc")
    observed = _ts(record.get("observed_at_utc"), "observed_at_utc")
    try:
        delay = float(record.get("minimum_hours_after_kickoff"))
    except (TypeError, ValueError) as exc:
        raise OutcomeError("NFL_V2G_OUTCOME_MIN_DELAY_INVALID") from exc
    _require(delay >= 5.0, "NFL_V2G_OUTCOME_MIN_DELAY_TOO_SHORT")
    _require(observed >= kickoff + timedelta(hours=delay), "NFL_V2G_OUTCOME_OBSERVED_TOO_EARLY")

    home_score = _score(record.get("home_score"), "home_score")
    away_score = _score(record.get("away_score"), "away_score")
    _require(record.get("final_margin_home_minus_away") == home_score - away_score,
             "NFL_V2G_OUTCOME_MARGIN_INCONSISTENT")
    _require(record.get("final_total") == home_score + away_score,
             "NFL_V2G_OUTCOME_TOTAL_INCONSISTENT")

    for key in (
        "promotion_authority", "may_create_model_p", "market_eligibility_changed",
        "truth_gate_pass_granted", "official_status_granted", "market_prices_consumed",
    ):
        _require(record.get(key) is False, f"NFL_V2G_OUTCOME_AUTHORITY_INVALID:{key}")
    expected = outcome_sha256(record)
    _require(str(record.get("outcome_sha256") or "").lower() == expected,
             "NFL_V2G_OUTCOME_SHA_MISMATCH")
    return expected


def _schedule_index(schedule_path: Path) -> dict[str, dict[str, str]]:
    with schedule_path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    out: dict[str, dict[str, str]] = {}
    for row in rows:
        game_id = str(row.get("game_id") or "").strip()
        if not game_id:
            continue
        if game_id in out:
            raise OutcomeError(f"NFL_V2G_OUTCOME_DUPLICATE_SCHEDULE_GAME:{game_id}")
        out[game_id] = row
    return out


def build_outcome(
    *,
    prediction: Mapping[str, Any],
    schedule_row: Mapping[str, Any],
    schedule_sha256: str,
    settlement_code_git_sha: str,
    observed_at_utc: str,
    min_hours_after_kickoff: float = 8.0,
) -> dict[str, Any] | None:
    prediction_sha = validate_prospective_prediction(prediction)
    game_id = str(prediction.get("game_id") or "").strip()
    _require(str(schedule_row.get("game_id") or "").strip() == game_id,
             "NFL_V2G_OUTCOME_GAME_ID_MISMATCH")
    _require(str(schedule_row.get("home_team") or "").strip() == str(prediction.get("home_team") or "").strip(),
             "NFL_V2G_OUTCOME_HOME_TEAM_MISMATCH")
    _require(str(schedule_row.get("away_team") or "").strip() == str(prediction.get("away_team") or "").strip(),
             "NFL_V2G_OUTCOME_AWAY_TEAM_MISMATCH")

    observed = _ts(observed_at_utc, "observed_at_utc")
    kickoff = _ts(prediction.get("kickoff_utc"), "kickoff_utc")
    _require(min_hours_after_kickoff >= 5.0, "NFL_V2G_OUTCOME_MIN_DELAY_TOO_SHORT")
    if observed < kickoff + timedelta(hours=float(min_hours_after_kickoff)):
        return None

    # nflverse leaves future-game scores blank. Once sufficiently post-kickoff,
    # blank scores remain pending rather than being imputed or inferred.
    if str(schedule_row.get("home_score") or "").strip() == "" or str(schedule_row.get("away_score") or "").strip() == "":
        return None
    home_score = _score(schedule_row.get("home_score"), "home_score")
    away_score = _score(schedule_row.get("away_score"), "away_score")

    code_sha = _hex(settlement_code_git_sha, bits=160, field="settlement_code_git_sha")
    source_sha = _hex(schedule_sha256, bits=256, field="result_schedule_snapshot_sha256")

    record: dict[str, Any] = {
        "schema_version": OUTCOME_SCHEMA,
        "status": "PROSPECTIVE_RESEARCH_OUTCOME_CAPTURED",
        "game_id": game_id,
        "season": int(prediction["season"]),
        "week": int(prediction["week"]),
        "kickoff_utc": prediction["kickoff_utc"],
        "observed_at_utc": observed.isoformat(),
        "home_team": prediction["home_team"],
        "away_team": prediction["away_team"],
        "home_score": home_score,
        "away_score": away_score,
        "final_margin_home_minus_away": home_score - away_score,
        "final_total": home_score + away_score,
        "prediction_sha256": prediction_sha,
        "artifact_sha256": prediction["artifact_sha256"],
        "prediction_capture_code_git_sha": prediction["capture_code_git_sha"],
        "settlement_code_git_sha": code_sha,
        "result_schedule_snapshot_sha256": source_sha,
        "minimum_hours_after_kickoff": float(min_hours_after_kickoff),
        "outcome_source": "NFLVERSE_GAMES_CSV_POSTGAME_SCORE",
        "market_prices_consumed": False,
        "promotion_authority": False,
        "may_create_model_p": False,
        "market_eligibility_changed": False,
        "truth_gate_pass_granted": False,
        "official_status_granted": False,
    }
    record["outcome_sha256"] = outcome_sha256(record)
    validate_outcome(record)
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions-dir", type=Path, required=True)
    parser.add_argument("--schedule", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--settlement-code-git-sha", required=True)
    parser.add_argument("--observed-at-utc", required=True)
    parser.add_argument("--min-hours-after-kickoff", type=float, default=8.0)
    args = parser.parse_args()

    schedule_bytes = args.schedule.read_bytes()
    schedule_sha = sha256(schedule_bytes).hexdigest()
    schedule = _schedule_index(args.schedule)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    created = 0
    pending = 0
    existing = 0
    for prediction_path in sorted(args.predictions_dir.glob("*.json")):
        prediction = json.loads(prediction_path.read_text(encoding="utf-8"))
        validate_prospective_prediction(prediction)
        game_id = str(prediction.get("game_id") or "").strip()
        schedule_row = schedule.get(game_id)
        if schedule_row is None:
            raise OutcomeError(f"NFL_V2G_OUTCOME_SCHEDULE_GAME_MISSING:{game_id}")
        destination = args.output_dir / f"{game_id}.json"
        if destination.exists():
            saved = json.loads(destination.read_text(encoding="utf-8"))
            validate_outcome(saved)
            _require(saved.get("prediction_sha256") == prediction.get("prediction_sha256"),
                     f"NFL_V2G_OUTCOME_EXISTING_PREDICTION_MISMATCH:{game_id}")
            existing += 1
            continue
        record = build_outcome(
            prediction=prediction,
            schedule_row=schedule_row,
            schedule_sha256=schedule_sha,
            settlement_code_git_sha=args.settlement_code_git_sha,
            observed_at_utc=args.observed_at_utc,
            min_hours_after_kickoff=args.min_hours_after_kickoff,
        )
        if record is None:
            pending += 1
            continue
        destination.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        created += 1

    print(json.dumps({
        "status": "NFL_V2G_PROSPECTIVE_OUTCOME_SETTLEMENT_COMPLETE",
        "created": created,
        "existing": existing,
        "pending": pending,
        "schedule_sha256": schedule_sha,
        "promotion_authority": False,
        "may_create_model_p": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
