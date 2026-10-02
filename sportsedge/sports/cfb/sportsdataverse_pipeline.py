"""Deterministic SportsDataverse training-row assembly for CFB candidate selection.

This module performs materialization only. It does not evaluate candidate families,
choose a winner, fit a serving artifact, create Model_P, start an evidence clock,
promote a market, or authorize betting.
"""
from __future__ import annotations

from hashlib import sha256
from typing import Any, Mapping, Sequence

from .sportsdataverse_history import (
    SOURCE_CONTRACT,
    build_prior_season_fallback_snapshots,
    build_season_week_snapshots,
    regular_fbs_schedule_rows,
)
from .sportsdataverse_manifest import canonical_sha256
from .sportsdataverse_materializer import materialize_native_candidate_inputs
from .sportsdataverse_training_rows import attach_training_labels
from .sportsdataverse_weather import bind_historical_weather, require_complete_weather
from .sportsdataverse_weather_transport import SOURCE_ID as WEATHER_SOURCE_ID

TRAINING_BUNDLE_SCHEMA = "CFB_SPORTSDATAVERSE_TRAINING_ROWS_V1"
FROZEN_START_SEASON = 2015
FROZEN_END_SEASON = 2025


class SDVTrainingPipelineError(ValueError):
    pass


def _strict_bool(value: Any, *, field: str, game_id: str) -> bool:
    if type(value) is bool:
        return value
    token = str(value or "").strip().lower()
    if token in {"true", "1", "t"}:
        return True
    if token in {"false", "0", "f"}:
        return False
    raise SDVTrainingPipelineError(
        f"CFB_SDV_SCHEDULE_BOOL_INVALID:{game_id}:{field}"
    )


def _completed_fbs_games(
    schedules: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    scoped = regular_fbs_schedule_rows(schedules)
    out: list[dict[str, Any]] = []
    for raw in scoped:
        row = dict(raw)
        gid = str(row.get("game_id") or "").strip()
        if not gid:
            raise SDVTrainingPipelineError("CFB_SDV_SCHEDULE_GAME_ID_REQUIRED")
        try:
            season = int(row["season"])
            week = int(row["week"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SDVTrainingPipelineError(
                f"CFB_SDV_SCHEDULE_SEASON_WEEK_INVALID:{gid}"
            ) from exc
        if not FROZEN_START_SEASON <= season <= FROZEN_END_SEASON:
            raise SDVTrainingPipelineError(
                f"CFB_SDV_SCHEDULE_SEASON_OUTSIDE_FROZEN_WINDOW:{gid}:{season}"
            )
        if week < 1:
            raise SDVTrainingPipelineError(f"CFB_SDV_SCHEDULE_WEEK_INVALID:{gid}")
        if not _strict_bool(row.get("completed"), field="completed", game_id=gid):
            continue
        for field in ("home_points", "away_points", "home_id", "away_id"):
            if row.get(field) in (None, ""):
                raise SDVTrainingPipelineError(
                    f"CFB_SDV_COMPLETED_GAME_FIELD_MISSING:{gid}:{field}"
                )
        out.append(row)
    return sorted(
        out,
        key=lambda r: (int(r["season"]), int(r["week"]), int(r["game_id"])),
    )


def _weather_index(
    weather_rows: Sequence[Mapping[str, Any]],
) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for raw in weather_rows:
        if not isinstance(raw, Mapping):
            raise SDVTrainingPipelineError("CFB_SDV_WEATHER_ROW_MAPPING_REQUIRED")
        try:
            gid = int(raw["game_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SDVTrainingPipelineError("CFB_SDV_WEATHER_GAME_ID_INVALID") from exc
        if gid in out:
            raise SDVTrainingPipelineError(f"CFB_SDV_WEATHER_DUPLICATE_GAME:{gid}")
        out[gid] = dict(raw)
    return out


def materialize_training_rows(
    *,
    schedules: Sequence[Mapping[str, Any]],
    adv_team_rows: Sequence[Mapping[str, Any]],
    adv_situational_rows: Sequence[Mapping[str, Any]],
    adv_drive_rows: Sequence[Mapping[str, Any]],
    weather_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Build the frozen 2015-2025 outcome-labeled candidate-selection rows."""
    completed = _completed_fbs_games(schedules)
    if not completed:
        raise SDVTrainingPipelineError("CFB_SDV_COMPLETED_FBS_GAMES_EMPTY")

    predictive: list[dict[str, Any]] = []
    for season in range(FROZEN_START_SEASON, FROZEN_END_SEASON + 1):
        season_games = [row for row in completed if int(row["season"]) == season]
        if not season_games:
            raise SDVTrainingPipelineError(f"CFB_SDV_SEASON_GAMES_EMPTY:{season}")
        current = build_season_week_snapshots(
            adv_team_rows=adv_team_rows,
            adv_situational_rows=adv_situational_rows,
            adv_drive_rows=adv_drive_rows,
            schedule_rows=schedules,
            season=season,
        )
        prior = []
        if season > FROZEN_START_SEASON:
            prior = build_prior_season_fallback_snapshots(
                adv_team_rows=adv_team_rows,
                adv_situational_rows=adv_situational_rows,
                adv_drive_rows=adv_drive_rows,
                schedule_rows=schedules,
                target_season=season,
            )
        predictive.extend(
            materialize_native_candidate_inputs(
                games=season_games,
                snapshots=current,
                prior_season_snapshots=prior,
            )
        )

    if not predictive:
        raise SDVTrainingPipelineError("CFB_SDV_PREDICTIVE_ROWS_EMPTY")

    weather = _weather_index(weather_rows)
    bound = [
        bind_historical_weather(row, weather.get(int(row["game_id"])))
        for row in predictive
    ]
    require_complete_weather(bound)

    predictive_ids = {str(row["game_id"]) for row in bound}
    label_games = [
        row for row in completed if str(row["game_id"]) in predictive_ids
    ]
    training = attach_training_labels(
        predictive_rows=bound,
        completed_games=label_games,
    )
    training.sort(
        key=lambda r: (int(r["season"]), int(r["week"]), int(r["game_id"]))
    )
    if any(int(row["season"]) >= 2026 for row in training):
        raise SDVTrainingPipelineError("CFB_SDV_2026_OUTCOMES_PROHIBITED")
    return training


def training_manifest(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    material = [dict(row) for row in rows]
    if not material:
        raise SDVTrainingPipelineError("CFB_SDV_TRAINING_ROWS_EMPTY")
    seasons = sorted({int(row["season"]) for row in material})
    if seasons[0] != FROZEN_START_SEASON or seasons[-1] != FROZEN_END_SEASON:
        raise SDVTrainingPipelineError("CFB_SDV_TRAINING_SEASON_COVERAGE_INVALID")
    ids = [str(row["game_id"]) for row in material]
    if len(ids) != len(set(ids)):
        raise SDVTrainingPipelineError("CFB_SDV_TRAINING_GAME_ID_DUPLICATE")
    game_id_bytes = "\n".join(sorted(ids)).encode("utf-8")
    core = {
        "schema": TRAINING_BUNDLE_SCHEMA,
        "status": "MATERIALIZED_RECONSTRUCTED_HISTORICAL_NOT_PIT",
        "source_contract": SOURCE_CONTRACT,
        "weather_source_id": WEATHER_SOURCE_ID,
        "training_window": {
            "start_season": FROZEN_START_SEASON,
            "end_season": FROZEN_END_SEASON,
            "season_type": "REGULAR",
            "classification": "FBS",
        },
        "row_count": len(material),
        "seasons": seasons,
        "game_ids_sha256": sha256(game_id_bytes).hexdigest(),
        "rows_sha256": canonical_sha256(material),
        "governance": {
            "attempts_consumed": 0,
            "evaluation_performed": False,
            "model_p_created": False,
            "promotion_authority": False,
            "official_authority": False,
        },
    }
    core["manifest_sha256"] = canonical_sha256(core)
    return core


__all__ = [
    "FROZEN_END_SEASON",
    "FROZEN_START_SEASON",
    "SDVTrainingPipelineError",
    "TRAINING_BUNDLE_SCHEMA",
    "materialize_training_rows",
    "training_manifest",
]
