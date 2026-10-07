#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.fit_nhl_public_baseline import _load_games
from sportsedge.sports.nhl.public_baseline_validation import validate_public_baseline

DEFAULT_PROTOCOL = Path("config/research/nhl_public_baseline_validation_protocol_v1.json")


def _load_protocol(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "NHL_PUBLIC_BASELINE_VALIDATION_PROTOCOL_V1":
        raise ValueError("NHL_PUBLIC_BASELINE_VALIDATION_PROTOCOL_INVALID")
    if payload.get("status") != "FROZEN_BEFORE_FIRST_REAL_DATA_EVALUATION":
        raise ValueError("NHL_PUBLIC_BASELINE_VALIDATION_PROTOCOL_NOT_FROZEN")
    if payload.get("allowed_game_types") != [2]:
        raise ValueError("NHL_PUBLIC_BASELINE_VALIDATION_GAME_TYPE_DRIFT")
    if payload.get("validated_bet_markets_remain_empty") is not True:
        raise ValueError("NHL_PUBLIC_BASELINE_VALIDATION_AUTHORITY_DRIFT")
    return payload


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    p.add_argument("--min-team-games", type=int, default=10)
    p.add_argument("--ridge", type=float, default=1.0)
    p.add_argument("--version", default="nhl-public-boxscore-baseline-v1")
    a = p.parse_args()

    protocol = _load_protocol(a.protocol)
    result = validate_public_baseline(
        _load_games(a.input),
        fit_before=protocol["fit_window"]["end_exclusive"],
        validate_start=protocol["validation_window"]["start_inclusive"],
        validate_before=protocol["validation_window"]["end_exclusive"],
        min_team_games=a.min_team_games,
        ridge=a.ridge,
        version=a.version,
    )
    payload = {
        "schema": "NHL_PUBLIC_BASELINE_VALIDATION_RESULT_V1",
        "protocol_schema": protocol["schema"],
        "protocol_status": protocol["status"],
        "training_rows": result.training_rows,
        "validation_rows": result.validation_rows,
        "team_goal_mae": result.team_goal_mae,
        "team_goal_rmse": result.team_goal_rmse,
        "poisson_negative_log_likelihood": result.poisson_negative_log_likelihood,
        "mean_predicted_regulation_goals": result.mean_predicted_regulation_goals,
        "mean_actual_regulation_goals": result.mean_actual_regulation_goals,
        "artifact": result.artifact.as_json_dict(),
        "evidence_role": result.evidence_role,
        "validated_bet_markets": [],
        "authority": {
            "research_only": True,
            "model_p": False,
            "truth_gate": False,
            "promotion": False,
            "staking": False,
            "official": False,
        },
    }
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "NHL_PUBLIC_BASELINE_RETROSPECTIVE_VALIDATION_COMPLETE",
        "training_rows": result.training_rows,
        "validation_rows": result.validation_rows,
        "validated_bet_markets": [],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
