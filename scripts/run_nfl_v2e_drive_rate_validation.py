#!/usr/bin/env python3
"""Run the final preregistered NFL V2E diagnostic with PIT drive-rate state."""
from __future__ import annotations

from math import isfinite
from pathlib import Path
import sys
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import scripts.run_nfl_v2e_candidate_validation as base
from sportsedge.sports.nfl.m2_v2e_candidate import (
    NFL_M2_V2E_PIT_STATE_FIELDS as _BASE_PIT_STATE_FIELDS,
)
from sportsedge.sports.nfl.m2_v2e_drive_rate import (
    V2E_DRIVE_RATE_CONTRACT,
    V2E_DRIVE_RATE_FIELD,
    V2E_DRIVE_RATE_SCOPE,
    build_v2e_pit_drive_rate_by_game,
)

_BASE_IDENTITY_SCHEDULE = base._identity_schedule
_BASE_DRIVE_BUILDER = base.build_v2e_drive_training_rows
_BASE_EVIDENCE_BUILDER = base.build_nfl_m2_v2e_candidate_evidence
_FINAL_PIT_STATE_FIELDS = tuple(_BASE_PIT_STATE_FIELDS) + (V2E_DRIVE_RATE_FIELD,)
_DRIVE_RATE_BY_GAME: dict[str, dict[str, float]] = {}


def _identity_schedule(
    schedule: list[dict],
    *,
    allowed_game_ids: set[str] | None = None,
) -> list[dict]:
    rows = _BASE_IDENTITY_SCHEDULE(schedule, allowed_game_ids=allowed_game_ids)
    source_by_game = {
        str(row.get("game_id") or ""): dict(row)
        for row in schedule
        if str(row.get("game_id") or "")
    }
    for row in rows:
        game_id = str(row.get("game_id") or "")
        source = source_by_game.get(game_id)
        if source is None or not str(source.get("gameday") or "").strip():
            raise SystemExit(f"NFL_M2_V2E_DRIVE_RATE_GAMEDAY_MISSING:{game_id}")
        row["gameday"] = source["gameday"]
    return rows


def _drive_builder(schedule_rows: list[dict], pbp_rows: list[dict]) -> list[dict]:
    rows = _BASE_DRIVE_BUILDER(schedule_rows, pbp_rows)
    global _DRIVE_RATE_BY_GAME
    _DRIVE_RATE_BY_GAME = build_v2e_pit_drive_rate_by_game(schedule_rows, rows)
    return rows


def _pit_state(features: object, *, side: str, game_id: str) -> dict[str, float]:
    if not isinstance(features, dict):
        raise SystemExit(f"NFL_M2_V2E_PIT_FEATURES_MISSING:{game_id}:{side}")
    state: dict[str, float] = {}
    for key in _BASE_PIT_STATE_FIELDS:
        if key not in features:
            raise SystemExit(f"NFL_M2_V2E_PIT_STATE_FIELD_MISSING:{game_id}:{side}:{key}")
        try:
            value = float(features[key])
        except (TypeError, ValueError) as exc:
            raise SystemExit(
                f"NFL_M2_V2E_PIT_STATE_FIELD_INVALID:{game_id}:{side}:{key}"
            ) from exc
        if not isfinite(value):
            raise SystemExit(f"NFL_M2_V2E_PIT_STATE_FIELD_INVALID:{game_id}:{side}:{key}")
        state[key] = value

    game_rates = _DRIVE_RATE_BY_GAME.get(game_id)
    if not isinstance(game_rates, dict) or side not in game_rates:
        raise SystemExit(f"NFL_M2_V2E_DRIVE_RATE_MISSING:{game_id}:{side}")
    drive_rate = float(game_rates[side])
    if not isfinite(drive_rate):
        raise SystemExit(f"NFL_M2_V2E_DRIVE_RATE_INVALID:{game_id}:{side}")
    state[V2E_DRIVE_RATE_FIELD] = drive_rate
    return state


def _evidence_builder(*args: Any, **kwargs: Any) -> dict[str, Any]:
    evidence = _BASE_EVIDENCE_BUILDER(*args, **kwargs)
    evidence.update(
        {
            "drive_rate_feature_name": V2E_DRIVE_RATE_FIELD,
            "drive_rate_feature_contract": V2E_DRIVE_RATE_CONTRACT,
            "drive_rate_history_scope": V2E_DRIVE_RATE_SCOPE,
            "drive_rate_point_in_time_proven": True,
            "drive_rate_current_game_excluded": True,
            "drive_rate_same_day_updates_deferred": True,
        }
    )
    return evidence


def _install_patches() -> None:
    # The base runner writes this exact tuple into the evidence artifact after
    # the candidate evaluator returns, so patch it to the final preregistered
    # 12-field state before invoking main.
    base.NFL_M2_V2E_PIT_STATE_FIELDS = _FINAL_PIT_STATE_FIELDS
    base._identity_schedule = _identity_schedule
    base.build_v2e_drive_training_rows = _drive_builder
    base._pit_state = _pit_state
    base.build_nfl_m2_v2e_candidate_evidence = _evidence_builder


def main() -> int:
    _install_patches()
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
