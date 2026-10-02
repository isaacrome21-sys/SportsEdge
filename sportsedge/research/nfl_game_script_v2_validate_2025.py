"""One-look 2025 validation for frozen NFL game-script V2.

This module is intentionally separate from the V2 fitter.  It consumes only
2025 regular-season target rows, uses each team's prior eight 2025 games as the
pregame workload baseline, and applies the frozen V2 script curve using realized
final team margin only for the predeclared held-out joint-distribution test.
"""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
from typing import Any, Mapping, Sequence

LOCK_PATH = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "research"
    / "nfl_game_script_v2_2025_validation_lock.json"
)

SCHEMA = "SPORTSEDGE_NFL_GAME_SCRIPT_V2_2025_VALIDATION"
LOCK_SCHEMA = "SPORTSEDGE_NFL_GAME_SCRIPT_V2_2025_VALIDATION_LOCK"
VALIDATION_SEASON = 2025
HISTORY_GAMES = 8
DECAY = 0.85
CANONICAL_ARTIFACT_SHA256 = (
    "8452beb9f37afd4ac6dac3a6860824fd47c4adfa352b21d25ddcf6223135972a"
)
CANONICAL_FIT_HEAD = "0643f6761e4670a82fd095935a4c814258e755c7"

MODEL_FIELDS = (
    "season",
    "season_type",
    "game_id",
    "posteam",
    "posteam_type",
    "home_score",
    "away_score",
    "pass_attempt",
    "rush_attempt",
    "qb_scramble",
    "qb_kneel",
)


class NflGameScriptV2ValidationError(ValueError):
    pass


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return sha256(raw).hexdigest()


def load_validation_lock(path: Path | None = None) -> dict[str, Any]:
    cfg = json.loads((path or LOCK_PATH).read_text())
    if cfg.get("schema") != LOCK_SCHEMA:
        raise NflGameScriptV2ValidationError("VALIDATION_LOCK_SCHEMA_INVALID")
    if cfg.get("status") != "FROZEN_BEFORE_2025_ACCESS":
        raise NflGameScriptV2ValidationError("VALIDATION_LOCK_STATUS_INVALID")

    fit = cfg.get("canonical_fit") or {}
    if fit.get("artifact_sha256") != CANONICAL_ARTIFACT_SHA256:
        raise NflGameScriptV2ValidationError("CANONICAL_ARTIFACT_SHA_DRIFT")
    if fit.get("fit_head_sha") != CANONICAL_FIT_HEAD:
        raise NflGameScriptV2ValidationError("CANONICAL_FIT_HEAD_DRIFT")
    if float(fit.get("selected_alpha")) != 10.0:
        raise NflGameScriptV2ValidationError("CANONICAL_ALPHA_DRIFT")
    if int(fit.get("n_team_games")) != 2560:
        raise NflGameScriptV2ValidationError("CANONICAL_FIT_N_DRIFT")

    source = cfg.get("validation_source") or {}
    if int(source.get("season")) != VALIDATION_SEASON:
        raise NflGameScriptV2ValidationError("VALIDATION_SEASON_DRIFT")
    if str(source.get("season_type")) != "REG":
        raise NflGameScriptV2ValidationError("VALIDATION_SEASON_TYPE_DRIFT")

    baseline = cfg.get("pregame_baseline") or {}
    if baseline.get("history_scope") != "2025_REGULAR_SEASON_ONLY":
        raise NflGameScriptV2ValidationError("VALIDATION_HISTORY_SCOPE_DRIFT")
    if int(baseline.get("prior_team_games")) != HISTORY_GAMES:
        raise NflGameScriptV2ValidationError("VALIDATION_HISTORY_GAMES_DRIFT")
    if float(baseline.get("decay")) != DECAY:
        raise NflGameScriptV2ValidationError("VALIDATION_DECAY_DRIFT")
    if baseline.get("cross_season_carry") is not False:
        raise NflGameScriptV2ValidationError("VALIDATION_CROSS_SEASON_FORBIDDEN")
    return cfg


def expected_validation_uri() -> str:
    return (
        "https://github.com/nflverse/nflverse-data/releases/download/pbp/"
        "play_by_play_2025.csv"
    )


def _num(value: Any, field: str) -> float:
    if value in (None, "") or isinstance(value, bool):
        raise NflGameScriptV2ValidationError(f"{field}:NUMERIC_REQUIRED")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise NflGameScriptV2ValidationError(f"{field}:NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise NflGameScriptV2ValidationError(f"{field}:NONFINITE")
    return out


def _int(value: Any, field: str) -> int:
    out = _num(value, field)
    if out != int(out):
        raise NflGameScriptV2ValidationError(f"{field}:INTEGER_REQUIRED")
    return int(out)


def _binary(value: Any, field: str) -> int:
    if value in (None, ""):
        return 0
    out = _int(value, field)
    if out not in (0, 1):
        raise NflGameScriptV2ValidationError(f"{field}:BINARY_REQUIRED")
    return out


def project_model_fields(raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise NflGameScriptV2ValidationError("PBP_ROW_OBJECT_REQUIRED")
    return {field: raw.get(field) for field in MODEL_FIELDS}


def _play_kind(row: Mapping[str, Any]) -> str | None:
    if _binary(row.get("qb_kneel"), "qb_kneel"):
        return None
    if _binary(row.get("qb_scramble"), "qb_scramble"):
        return "RUSH"
    if _binary(row.get("pass_attempt"), "pass_attempt"):
        return "PASS"
    if _binary(row.get("rush_attempt"), "rush_attempt"):
        return "RUSH"
    return None


def _team_margin(row: Mapping[str, Any]) -> int:
    home = _int(row.get("home_score"), "home_score")
    away = _int(row.get("away_score"), "away_score")
    side = str(row.get("posteam_type") or "").strip().lower()
    if side == "home":
        return home - away
    if side == "away":
        return away - home
    raise NflGameScriptV2ValidationError("POSTEAM_TYPE_HOME_AWAY_REQUIRED")


def _game_week(game_id: str) -> int:
    parts = str(game_id).split("_")
    if len(parts) < 2:
        raise NflGameScriptV2ValidationError(f"GAME_ID_WEEK_UNPARSABLE:{game_id}")
    try:
        week = int(parts[1])
    except ValueError as exc:
        raise NflGameScriptV2ValidationError(
            f"GAME_ID_WEEK_UNPARSABLE:{game_id}"
        ) from exc
    if not 1 <= week <= 18:
        raise NflGameScriptV2ValidationError(f"REG_WEEK_OUT_OF_RANGE:{game_id}:{week}")
    return week


def build_validation_team_games(
    pbp_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in pbp_rows:
        row = project_model_fields(raw)
        if str(row.get("season_type") or "").strip().upper() != "REG":
            continue
        season = _int(row.get("season"), "season")
        if season != VALIDATION_SEASON:
            raise NflGameScriptV2ValidationError(
                f"VALIDATION_ROW_OUTSIDE_2025:{season}"
            )
        game_id = str(row.get("game_id") or "").strip()
        team = str(row.get("posteam") or "").strip().upper()
        if not game_id or not team:
            continue
        kind = _play_kind(row)
        if kind is None:
            continue
        margin = _team_margin(row)
        key = (game_id, team)
        current = grouped.setdefault(
            key,
            {
                "season": season,
                "week": _game_week(game_id),
                "game_id": game_id,
                "team": team,
                "final_margin": margin,
                "pass_plays": 0,
                "rush_plays": 0,
            },
        )
        if current["final_margin"] != margin:
            raise NflGameScriptV2ValidationError(
                f"FINAL_MARGIN_INCONSISTENT:{game_id}:{team}"
            )
        current["pass_plays" if kind == "PASS" else "rush_plays"] += 1

    rows = sorted(
        grouped.values(),
        key=lambda r: (r["team"], r["week"], r["game_id"]),
    )
    if not rows:
        raise NflGameScriptV2ValidationError("VALIDATION_TEAM_GAME_ROWS_EMPTY")

    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row["game_id"], row["team"])
        if key in seen:
            raise NflGameScriptV2ValidationError(
                f"VALIDATION_TEAM_GAME_DUPLICATE:{row['game_id']}:{row['team']}"
            )
        seen.add(key)
        if row["pass_plays"] <= 0 or row["rush_plays"] <= 0:
            raise NflGameScriptV2ValidationError(
                f"VALIDATION_WORKLOAD_NONPOSITIVE:{row['game_id']}:{row['team']}"
            )
    return rows


def _basis(margin: float) -> list[float]:
    m = float(margin)
    return [
        1.0,
        m,
        max(0.0, m + 14.0),
        max(0.0, m + 7.0),
        max(0.0, m),
        max(0.0, m - 7.0),
        max(0.0, m - 14.0),
    ]


def _predict_model(model: Mapping[str, Any], margin: float) -> float:
    raw = _basis(margin)
    means = [float(x) for x in model["means"]]
    scales = [float(x) for x in model["scales"]]
    coef = [float(x) for x in model["coef"]]
    if not (len(raw) == len(means) == len(scales) == len(coef) == 7):
        raise NflGameScriptV2ValidationError("CANONICAL_MODEL_DIMENSION_INVALID")
    z = [1.0]
    for j in range(1, len(raw)):
        if scales[j] <= 0:
            raise NflGameScriptV2ValidationError("CANONICAL_MODEL_SCALE_INVALID")
        z.append((raw[j] - means[j]) / scales[j])
    return sum(c * x for c, x in zip(coef, z))


def script_multipliers(
    lock: Mapping[str, Any],
    *,
    final_margin: float,
) -> dict[str, float]:
    fit = lock["canonical_fit"]
    pass_multiplier = _predict_model(fit["pass_model"], final_margin)
    rush_multiplier = _predict_model(fit["rush_model"], final_margin)
    for name, value in (
        ("pass_multiplier", pass_multiplier),
        ("rush_multiplier", rush_multiplier),
    ):
        if not 0.4 <= value <= 1.8:
            raise NflGameScriptV2ValidationError(
                f"CANONICAL_MULTIPLIER_OUT_OF_RANGE:{final_margin}:{name}:{value}"
            )
    return {
        "pass_multiplier": pass_multiplier,
        "rush_multiplier": rush_multiplier,
    }


def _weighted_prior(
    history: Sequence[Mapping[str, Any]],
    field: str,
) -> float:
    if len(history) < HISTORY_GAMES:
        raise NflGameScriptV2ValidationError("PRIOR_HISTORY_INSUFFICIENT")
    window = list(history[-HISTORY_GAMES:])
    weighted = 0.0
    total_weight = 0.0
    for age, row in enumerate(reversed(window)):
        weight = DECAY ** age
        weighted += weight * float(row[field])
        total_weight += weight
    if total_weight <= 0:
        raise NflGameScriptV2ValidationError("PRIOR_WEIGHT_ZERO")
    return weighted / total_weight


def _mae(rows: Sequence[Mapping[str, Any]], field: str) -> float:
    if not rows:
        raise NflGameScriptV2ValidationError("VALIDATION_EVAL_ROWS_EMPTY")
    return sum(abs(float(row[field])) for row in rows) / len(rows)


def _mean(rows: Sequence[Mapping[str, Any]], field: str) -> float:
    if not rows:
        raise NflGameScriptV2ValidationError("VALIDATION_EVAL_ROWS_EMPTY")
    return sum(float(row[field]) for row in rows) / len(rows)


def score_evaluation_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    lock: Mapping[str, Any],
) -> dict[str, Any]:
    baseline_pass_mae = _mae(rows, "baseline_pass_error")
    baseline_rush_mae = _mae(rows, "baseline_rush_error")
    script_pass_mae = _mae(rows, "script_pass_error")
    script_rush_mae = _mae(rows, "script_rush_error")

    baseline_combined = 0.5 * (baseline_pass_mae + baseline_rush_mae)
    script_combined = 0.5 * (script_pass_mae + script_rush_mae)
    if baseline_combined <= 0:
        raise NflGameScriptV2ValidationError("BASELINE_COMBINED_MAE_NONPOSITIVE")
    relative_improvement = (
        baseline_combined - script_combined
    ) / baseline_combined

    pass_mean_error = _mean(rows, "script_pass_signed_error")
    rush_mean_error = _mean(rows, "script_rush_signed_error")

    gate_cfg = lock["gates"]
    gates = {
        "combined_mae_relative_improvement": (
            relative_improvement
            >= float(gate_cfg["combined_mae_relative_improvement_min"])
        ),
        "pass_mae_not_worsen": (
            script_pass_mae <= baseline_pass_mae + 1e-12
        ),
        "rush_mae_not_worsen": (
            script_rush_mae <= baseline_rush_mae + 1e-12
        ),
        "pass_mean_error_abs": (
            abs(pass_mean_error)
            <= float(gate_cfg["pass_mean_error_abs_max_plays"]) + 1e-12
        ),
        "rush_mean_error_abs": (
            abs(rush_mean_error)
            <= float(gate_cfg["rush_mean_error_abs_max_plays"]) + 1e-12
        ),
    }
    passed = all(gates.values())
    return {
        "baseline": {
            "pass_mae": baseline_pass_mae,
            "rush_mae": baseline_rush_mae,
            "combined_mae": baseline_combined,
        },
        "scripted": {
            "pass_mae": script_pass_mae,
            "rush_mae": script_rush_mae,
            "combined_mae": script_combined,
            "pass_mean_error": pass_mean_error,
            "rush_mean_error": rush_mean_error,
        },
        "combined_mae_relative_improvement": relative_improvement,
        "gates": gates,
        "passed": passed,
    }


def validate_2025(
    team_games: Sequence[Mapping[str, Any]],
    *,
    source_receipt: Mapping[str, Any],
    lock: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = dict(lock or load_validation_lock())
    source_uri = str(source_receipt.get("source_uri") or "")
    if source_uri != expected_validation_uri():
        raise NflGameScriptV2ValidationError("VALIDATION_SOURCE_URI_INVALID")
    digest = str(source_receipt.get("raw_sha256") or "").lower()
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise NflGameScriptV2ValidationError("VALIDATION_SOURCE_SHA256_INVALID")
    if int(source_receipt.get("season") or 0) != VALIDATION_SEASON:
        raise NflGameScriptV2ValidationError("VALIDATION_SOURCE_SEASON_INVALID")
    if not str(source_receipt.get("retrieved_at") or "").strip():
        raise NflGameScriptV2ValidationError("VALIDATION_SOURCE_RETRIEVED_AT_REQUIRED")

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in team_games:
        row = dict(raw)
        if int(row.get("season") or 0) != VALIDATION_SEASON:
            raise NflGameScriptV2ValidationError(
                f"VALIDATION_TEAM_GAME_OUTSIDE_2025:{row.get('season')}"
            )
        groups[str(row["team"]).upper()].append(row)

    eval_rows: list[dict[str, Any]] = []
    for team, rows in sorted(groups.items()):
        ordered = sorted(rows, key=lambda r: (int(r["week"]), str(r["game_id"])))
        history: list[dict[str, Any]] = []
        last_week = 0
        for row in ordered:
            week = int(row["week"])
            if week <= last_week:
                raise NflGameScriptV2ValidationError(
                    f"TEAM_GAME_ORDER_NONINCREASING:{team}:{week}"
                )
            if len(history) >= HISTORY_GAMES:
                pass_base = _weighted_prior(history, "pass_plays")
                rush_base = _weighted_prior(history, "rush_plays")
                multipliers = script_multipliers(
                    cfg, final_margin=float(row["final_margin"])
                )
                pass_pred = pass_base * multipliers["pass_multiplier"]
                rush_pred = rush_base * multipliers["rush_multiplier"]
                actual_pass = float(row["pass_plays"])
                actual_rush = float(row["rush_plays"])
                eval_rows.append(
                    {
                        "team": team,
                        "week": week,
                        "game_id": row["game_id"],
                        "final_margin": int(row["final_margin"]),
                        "history_game_ids": [
                            str(x["game_id"]) for x in history[-HISTORY_GAMES:]
                        ],
                        "baseline_pass": pass_base,
                        "baseline_rush": rush_base,
                        "pass_multiplier": multipliers["pass_multiplier"],
                        "rush_multiplier": multipliers["rush_multiplier"],
                        "script_pass": pass_pred,
                        "script_rush": rush_pred,
                        "actual_pass": actual_pass,
                        "actual_rush": actual_rush,
                        "baseline_pass_error": pass_base - actual_pass,
                        "baseline_rush_error": rush_base - actual_rush,
                        "script_pass_error": pass_pred - actual_pass,
                        "script_rush_error": rush_pred - actual_rush,
                        "script_pass_signed_error": pass_pred - actual_pass,
                        "script_rush_signed_error": rush_pred - actual_rush,
                    }
                )
            history.append(row)
            last_week = week

    if not eval_rows:
        raise NflGameScriptV2ValidationError("VALIDATION_NO_ELIGIBLE_TEAM_GAMES")

    metrics = score_evaluation_rows(eval_rows, lock=cfg)
    status = "VALIDATION_PASS" if metrics["passed"] else "VALIDATION_FAIL"
    evaluated_weeks = sorted({int(row["week"]) for row in eval_rows})
    artifact: dict[str, Any] = {
        "schema": SCHEMA,
        "status": status,
        "validation_window_spent": True,
        "validation_season": VALIDATION_SEASON,
        "canonical_fit_artifact_sha256": CANONICAL_ARTIFACT_SHA256,
        "canonical_fit_head_sha": CANONICAL_FIT_HEAD,
        "validation_lock_sha256": canonical_sha256(cfg),
        "source_receipt": {
            "season": VALIDATION_SEASON,
            "source_uri": source_uri,
            "raw_sha256": digest,
            "retrieved_at": str(source_receipt["retrieved_at"]),
            "raw_bytes": int(source_receipt.get("raw_bytes") or 0),
        },
        "history_policy": {
            "scope": "2025_REGULAR_SEASON_ONLY",
            "prior_team_games": HISTORY_GAMES,
            "decay": DECAY,
            "cross_season_carry": False,
        },
        "n_teams": len(groups),
        "n_evaluated_team_games": len(eval_rows),
        "evaluated_weeks": evaluated_weeks,
        "metrics": metrics,
        "evaluation_rows": eval_rows,
        "post_result_policy": {
            "v2_retune_allowed": False,
            "second_2025_look_allowed": False,
            "separate_integration_pr_allowed": bool(metrics["passed"]),
        },
        "authority": {
            "research_only": True,
            "changes_attempt9_owner": False,
            "creates_model_p": False,
            "truth_gate_authority": False,
            "official_authority": False,
            "promotion_authority": False,
            "staking_authority": False,
        },
    }
    artifact["artifact_sha256"] = canonical_sha256(artifact)
    return artifact


__all__ = [
    "CANONICAL_ARTIFACT_SHA256",
    "CANONICAL_FIT_HEAD",
    "DECAY",
    "HISTORY_GAMES",
    "MODEL_FIELDS",
    "NflGameScriptV2ValidationError",
    "VALIDATION_SEASON",
    "build_validation_team_games",
    "canonical_sha256",
    "expected_validation_uri",
    "load_validation_lock",
    "project_model_fields",
    "score_evaluation_rows",
    "script_multipliers",
    "validate_2025",
]
