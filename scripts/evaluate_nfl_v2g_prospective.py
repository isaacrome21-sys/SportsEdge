#!/usr/bin/env python3
"""First-write evaluation of immutable NFL V2G prospective research predictions.

This evaluator is deliberately market-blind and research-only. It consumes only:
- an already captured, hash-valid prospective V2G prediction; and
- an NFL schedule/result snapshot with final home/away scores.

It cannot create Model_P, promotion authority, market eligibility, Truth Gate PASS,
OFFICIAL status, staking output, or football prop output.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.nfl.m2_v2g_forward import validate_prospective_prediction

EVALUATION_SCHEMA = "NFL_M2_V2G_PROSPECTIVE_EVALUATION_V1"
EVALUATION_STATUS = "PROSPECTIVE_RESEARCH_EVALUATION_COMPLETE"


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_MAPPING_REQUIRED:{path}")
    return value


def _parse_time(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"NFL_V2G_EVAL_TIMESTAMP_INVALID:{field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"NFL_V2G_EVAL_TIMESTAMP_TZ_REQUIRED:{field}")
    return parsed.astimezone(timezone.utc)


def _hex(value: str, length: int, field: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != length or any(ch not in "0123456789abcdef" for ch in text):
        raise ValueError(f"NFL_V2G_EVAL_HASH_INVALID:{field}")
    return text


def _score(value: str | None) -> int | None:
    text = str(value or "").strip()
    if not text or text.upper() in {"NA", "NAN", "NONE", "NULL"}:
        return None
    try:
        number = int(float(text))
    except ValueError as exc:
        raise ValueError(f"NFL_V2G_EVAL_SCORE_INVALID:{text}") from exc
    if number < 0:
        raise ValueError(f"NFL_V2G_EVAL_SCORE_NEGATIVE:{number}")
    return number


def _load_results(schedule: Path) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    with schedule.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            game_id = str(row.get("game_id") or "").strip()
            if game_id:
                rows[game_id] = row
    return rows


def _three_way_brier(prediction: dict, home_score: int, away_score: int) -> float:
    summary = prediction.get("summary")
    if not isinstance(summary, dict):
        raise ValueError("NFL_V2G_EVAL_SUMMARY_REQUIRED")
    probs = [
        float(summary["home_win_probability"]),
        float(summary["tie_probability"]),
        float(summary["away_win_probability"]),
    ]
    if not all(isfinite(p) and 0.0 <= p <= 1.0 for p in probs):
        raise ValueError("NFL_V2G_EVAL_OUTCOME_PROBABILITY_INVALID")
    if abs(sum(probs) - 1.0) > 1e-9:
        raise ValueError("NFL_V2G_EVAL_OUTCOME_MASS_INVALID")
    realized = [0.0, 0.0, 0.0]
    realized[0 if home_score > away_score else 1 if home_score == away_score else 2] = 1.0
    return sum((p - y) ** 2 for p, y in zip(probs, realized))


def _evaluate(prediction: dict, result: dict[str, str], *, evaluated_at: datetime,
              schedule_sha256: str, evaluator_blob_sha1: str, workflow_blob_sha1: str) -> dict | None:
    validate_prospective_prediction(prediction)
    kickoff = _parse_time(prediction["kickoff_utc"], "kickoff_utc")
    if evaluated_at <= kickoff:
        return None

    home_score = _score(result.get("home_score"))
    away_score = _score(result.get("away_score"))
    if home_score is None or away_score is None:
        return None

    expected_identity = {
        "season": str(prediction["season"]),
        "week": str(prediction["week"]),
        "home_team": str(prediction["home_team"]),
        "away_team": str(prediction["away_team"]),
    }
    for field, wanted in expected_identity.items():
        actual = str(result.get(field) or "").strip()
        if actual != wanted:
            raise ValueError(f"NFL_V2G_EVAL_RESULT_IDENTITY_MISMATCH:{field}")

    summary = prediction.get("summary")
    if not isinstance(summary, dict):
        raise ValueError("NFL_V2G_EVAL_SUMMARY_REQUIRED")
    expected_home = float(summary["expected_home_score"])
    expected_away = float(summary["expected_away_score"])
    if not isfinite(expected_home) or not isfinite(expected_away):
        raise ValueError("NFL_V2G_EVAL_EXPECTED_SCORE_NONFINITE")

    expected_margin = expected_home - expected_away
    expected_total = expected_home + expected_away
    realized_margin = home_score - away_score
    realized_total = home_score + away_score
    margin_error = expected_margin - realized_margin
    total_error = expected_total - realized_total

    record = {
        "schema_version": EVALUATION_SCHEMA,
        "status": EVALUATION_STATUS,
        "game_id": str(prediction["game_id"]),
        "season": int(prediction["season"]),
        "week": int(prediction["week"]),
        "home_team": str(prediction["home_team"]),
        "away_team": str(prediction["away_team"]),
        "kickoff_utc": str(prediction["kickoff_utc"]),
        "captured_at_utc": str(prediction["captured_at_utc"]),
        "evaluated_at_utc": evaluated_at.isoformat(),
        "prediction_sha256": str(prediction["prediction_sha256"]).lower(),
        "artifact_sha256": str(prediction["artifact_sha256"]).lower(),
        "result_schedule_snapshot_sha256": schedule_sha256,
        "evaluation_code_git_blob_sha1": evaluator_blob_sha1,
        "evaluation_workflow_git_blob_sha1": workflow_blob_sha1,
        "expected_home_score": expected_home,
        "expected_away_score": expected_away,
        "expected_margin_home_minus_away": expected_margin,
        "expected_total": expected_total,
        "realized_home_score": home_score,
        "realized_away_score": away_score,
        "realized_margin_home_minus_away": realized_margin,
        "realized_total": realized_total,
        "margin_error_predicted_minus_realized": margin_error,
        "absolute_margin_error": abs(margin_error),
        "total_error_predicted_minus_realized": total_error,
        "absolute_total_error": abs(total_error),
        "score_mae": (abs(expected_home - home_score) + abs(expected_away - away_score)) / 2.0,
        "three_way_outcome_brier": _three_way_brier(prediction, home_score, away_score),
        "historical_data_role": "GENUINE_PROSPECTIVE_RESEARCH_EVALUATION",
        "market_prices_consumed": False,
        "promotion_authority": False,
        "may_create_model_p": False,
        "market_eligibility_changed": False,
        "truth_gate_pass_granted": False,
        "official_status_granted": False,
        "nfl_props": "NO_ENGINE",
    }
    return record


def _validate_existing(existing: dict, prediction: dict) -> None:
    if existing.get("schema_version") != EVALUATION_SCHEMA or existing.get("status") != EVALUATION_STATUS:
        raise ValueError("NFL_V2G_EVAL_EXISTING_SCHEMA_INVALID")
    if str(existing.get("game_id") or "") != str(prediction["game_id"]):
        raise ValueError("NFL_V2G_EVAL_EXISTING_GAME_MISMATCH")
    if str(existing.get("prediction_sha256") or "").lower() != str(prediction["prediction_sha256"]).lower():
        raise ValueError("NFL_V2G_EVAL_EXISTING_PREDICTION_MISMATCH")
    for field in (
        "market_prices_consumed", "promotion_authority", "may_create_model_p",
        "market_eligibility_changed", "truth_gate_pass_granted", "official_status_granted",
    ):
        if existing.get(field) is not False:
            raise ValueError(f"NFL_V2G_EVAL_EXISTING_GOVERNANCE_INVALID:{field}")
    if existing.get("nfl_props") != "NO_ENGINE":
        raise ValueError("NFL_V2G_EVAL_EXISTING_PROP_STATUS_INVALID")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--predictions-dir", type=Path, required=True)
    ap.add_argument("--schedule", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--snapshot-output-dir", type=Path)
    ap.add_argument("--evaluation-code-git-blob-sha1", required=True)
    ap.add_argument("--workflow-git-blob-sha1", required=True)
    ap.add_argument("--evaluated-at-utc")
    args = ap.parse_args()

    evaluator_blob = _hex(args.evaluation_code_git_blob_sha1, 40, "evaluation_code_git_blob_sha1")
    workflow_blob = _hex(args.workflow_git_blob_sha1, 40, "workflow_git_blob_sha1")
    evaluated_at = (
        _parse_time(args.evaluated_at_utc, "evaluated_at_utc")
        if args.evaluated_at_utc else datetime.now(timezone.utc)
    )
    schedule_bytes = args.schedule.read_bytes()
    schedule_sha = sha256(schedule_bytes).hexdigest()
    results = _load_results(args.schedule)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    skipped_existing: list[str] = []
    not_final: list[str] = []
    for path in sorted(args.predictions_dir.glob("*.json")):
        prediction = _read_json(path)
        validate_prospective_prediction(prediction)
        game_id = str(prediction["game_id"])
        result = results.get(game_id)
        if result is None:
            not_final.append(game_id)
            continue
        output = args.output_dir / f"{game_id}.json"
        if output.exists():
            _validate_existing(_read_json(output), prediction)
            skipped_existing.append(game_id)
            continue
        record = _evaluate(
            prediction, result, evaluated_at=evaluated_at, schedule_sha256=schedule_sha,
            evaluator_blob_sha1=evaluator_blob, workflow_blob_sha1=workflow_blob,
        )
        if record is None:
            not_final.append(game_id)
            continue
        output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        created.append(game_id)

    if created and args.snapshot_output_dir is not None:
        args.snapshot_output_dir.mkdir(parents=True, exist_ok=True)
        snapshot = args.snapshot_output_dir / f"{schedule_sha}.csv"
        if snapshot.exists():
            if sha256(snapshot.read_bytes()).hexdigest() != schedule_sha:
                raise ValueError("NFL_V2G_EVAL_SNAPSHOT_HASH_MISMATCH")
        else:
            shutil.copyfile(args.schedule, snapshot)

    print(json.dumps({
        "status": "NEW_PROSPECTIVE_EVALUATIONS" if created else "NO_NEW_FINAL_RESULTS",
        "evaluated_at_utc": evaluated_at.isoformat(),
        "result_schedule_snapshot_sha256": schedule_sha,
        "new_evaluation_count": len(created),
        "skipped_existing_count": len(skipped_existing),
        "not_final_count": len(not_final),
        "new_game_ids": created,
        "promotion_authority": False,
        "may_create_model_p": False,
        "official_status_granted": False,
        "nfl_props": "NO_ENGINE",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
