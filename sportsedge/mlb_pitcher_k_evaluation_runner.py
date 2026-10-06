"""Fail-closed runner for the frozen MLB pitcher-K historical evaluation.

Consumes only already-assembled PIT-safe historical rows. Acquisition remains a
separate concern so evaluation is deterministic and rerunnable from a frozen row
artifact.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .mlb_pitcher_k_probability_evaluator import evaluate_pitcher_k_candidate

ROW_SCHEMA = "MLB_PITCHER_K_HISTORICAL_EVALUATION_ROW_V1"
ARTIFACT_SCHEMA = "MLB_PITCHER_K_HISTORICAL_EVALUATION_ARTIFACT_V1"
EXPECTED_SEASONS = {2023, 2024, 2025}


class PitcherKEvaluationRunnerError(ValueError):
    pass


def _validate_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence) or not rows:
        raise PitcherKEvaluationRunnerError("historical evaluation rows required")
    clean: list[dict[str, Any]] = []
    seasons: set[int] = set()
    identities: set[tuple[int, int, str]] = set()
    for raw in rows:
        if not isinstance(raw, Mapping) or raw.get("schema") != ROW_SCHEMA:
            raise PitcherKEvaluationRunnerError("unexpected historical row schema")
        if raw.get("historical_reconstruction") is not True or raw.get("backfill") is not True:
            raise PitcherKEvaluationRunnerError("historical reconstruction flags required")
        if raw.get("forward_evidence_eligible") is not False or raw.get("promotion_authority") is not False:
            raise PitcherKEvaluationRunnerError("historical rows cannot grant forward/promotion authority")
        season = int(raw.get("season"))
        if season not in EXPECTED_SEASONS:
            raise PitcherKEvaluationRunnerError("row season outside frozen split")
        target_date = str(raw.get("target_date") or "")
        if not target_date.startswith(f"{season}-"):
            raise PitcherKEvaluationRunnerError("target date/season mismatch")
        game_id = int(raw.get("game_id"))
        pitcher_id = str(raw.get("pitcher_id") or "").strip()
        if not pitcher_id:
            raise PitcherKEvaluationRunnerError("pitcher_id required")
        identity = (season, game_id, pitcher_id)
        if identity in identities:
            raise PitcherKEvaluationRunnerError("duplicate season/game/pitcher row")
        identities.add(identity)
        seasons.add(season)
        clean.append(dict(raw))
    if seasons != EXPECTED_SEASONS:
        raise PitcherKEvaluationRunnerError("all frozen split seasons required")
    return clean


def evaluate_frozen_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    clean = _validate_rows(rows)
    row_payload = json.dumps(clean, sort_keys=True, separators=(",", ":"), allow_nan=False)
    result = evaluate_pitcher_k_candidate(clean)
    artifact = {
        "schema": ARTIFACT_SCHEMA,
        "row_count": len(clean),
        "rows_sha256": sha256(row_payload.encode()).hexdigest(),
        "authority": {
            "model_p": False,
            "truth_gate": False,
            "promotion": False,
            "staking": False,
            "official": False,
            "bettor_facing_release": False,
        },
        "evaluation": result,
    }
    digest = json.dumps(artifact, sort_keys=True, separators=(",", ":"), allow_nan=False)
    artifact["artifact_sha256"] = sha256(digest.encode()).hexdigest()
    return artifact


def run_file(input_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    source = Path(input_path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    rows = payload.get("rows") if isinstance(payload, Mapping) else payload
    artifact = evaluate_frozen_rows(rows)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(artifact, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return artifact
