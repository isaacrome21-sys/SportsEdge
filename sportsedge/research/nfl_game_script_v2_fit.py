"""NFL game-script V2 research fit.

Fresh development window: 2011-2015 only.
The failed V1 development window (2016-2024) and clean 2025 validation season
are not accepted by this fitter.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

import numpy as np

PRELOCK_PATH = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "research"
    / "nfl_game_script_v2_prelock.json"
)

SCHEMA = "SPORTSEDGE_NFL_GAME_SCRIPT_V2_ARTIFACT"
STATUS = "FITTED_RESEARCH_ONLY_NOT_VALIDATED"
DEVELOPMENT_SEASONS = (2011, 2012, 2013, 2014, 2015)
EXPOSED_V1_SEASONS = tuple(range(2016, 2025))
VALIDATION_SEASON = 2025
ALPHAS = (0.1, 1.0, 10.0, 100.0)
KNOTS = (-14.0, -7.0, 0.0, 7.0, 14.0)
MIN_TEAM_SEASON_GAMES = 8
MULTIPLIER_MIN = 0.40
MULTIPLIER_MAX = 1.80
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

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


class NflGameScriptV2Error(ValueError):
    pass


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return sha256(raw).hexdigest()


def load_prelock(path: Path | None = None) -> dict[str, Any]:
    cfg = json.loads((path or PRELOCK_PATH).read_text())
    if cfg.get("schema") != "SPORTSEDGE_NFL_GAME_SCRIPT_V2_PRELOCK":
        raise NflGameScriptV2Error("GAME_SCRIPT_V2_PRELOCK_SCHEMA_INVALID")
    if cfg.get("status") != "FROZEN_BEFORE_V2_SCORING":
        raise NflGameScriptV2Error("GAME_SCRIPT_V2_PRELOCK_STATUS_INVALID")
    if tuple(int(x) for x in cfg["fit_window"]["seasons"]) != DEVELOPMENT_SEASONS:
        raise NflGameScriptV2Error("GAME_SCRIPT_V2_FIT_WINDOW_DRIFT")
    if tuple(int(x) for x in cfg["excluded_from_v2_fit_or_selection"]["seasons"]) != EXPOSED_V1_SEASONS:
        raise NflGameScriptV2Error("GAME_SCRIPT_V2_EXPOSED_WINDOW_DRIFT")
    if int(cfg["validation_window"]["season"]) != VALIDATION_SEASON:
        raise NflGameScriptV2Error("GAME_SCRIPT_V2_VALIDATION_WINDOW_DRIFT")
    return cfg


def expected_pbp_uri(season: int) -> str:
    return (
        "https://github.com/nflverse/nflverse-data/releases/download/pbp/"
        f"play_by_play_{int(season)}.csv"
    )


def _number(value: Any, field: str) -> float:
    if value in (None, "") or isinstance(value, bool):
        raise NflGameScriptV2Error(f"{field}:NUMERIC_REQUIRED")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise NflGameScriptV2Error(f"{field}:NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise NflGameScriptV2Error(f"{field}:NONFINITE")
    return out


def _integer(value: Any, field: str) -> int:
    out = _number(value, field)
    if out != int(out):
        raise NflGameScriptV2Error(f"{field}:INTEGER_REQUIRED")
    return int(out)


def _binary(value: Any, field: str) -> int:
    if value in (None, ""):
        return 0
    out = _integer(value, field)
    if out not in (0, 1):
        raise NflGameScriptV2Error(f"{field}:BINARY_REQUIRED")
    return out


def _development_season(value: Any) -> int:
    season = _integer(value, "season")
    if season not in DEVELOPMENT_SEASONS:
        raise NflGameScriptV2Error(f"V2_ROW_OUTSIDE_DEVELOPMENT_WINDOW:{season}")
    return season


def project_model_fields(raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise NflGameScriptV2Error("PBP_ROW_OBJECT_REQUIRED")
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
    home = _integer(row.get("home_score"), "home_score")
    away = _integer(row.get("away_score"), "away_score")
    side = str(row.get("posteam_type") or "").strip().lower()
    if side == "home":
        return home - away
    if side == "away":
        return away - home
    raise NflGameScriptV2Error("POSTEAM_TYPE_HOME_AWAY_REQUIRED")


def build_team_game_rows(
    pbp_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, str, str], dict[str, Any]] = {}
    for raw in pbp_rows:
        row = project_model_fields(raw)
        if str(row.get("season_type") or "").strip().upper() != "REG":
            continue
        season = _development_season(row.get("season"))
        game_id = str(row.get("game_id") or "").strip()
        team = str(row.get("posteam") or "").strip().upper()
        if not game_id or not team:
            continue
        kind = _play_kind(row)
        if kind is None:
            continue
        margin = _team_margin(row)
        key = (season, game_id, team)
        current = grouped.setdefault(
            key,
            {
                "season": season,
                "game_id": game_id,
                "team": team,
                "final_margin": margin,
                "pass_plays": 0,
                "rush_plays": 0,
            },
        )
        if current["final_margin"] != margin:
            raise NflGameScriptV2Error(f"GAME_FINAL_MARGIN_INCONSISTENT:{game_id}:{team}")
        current["pass_plays" if kind == "PASS" else "rush_plays"] += 1

    rows = sorted(grouped.values(), key=lambda r: (r["season"], r["game_id"], r["team"]))
    if not rows:
        raise NflGameScriptV2Error("TEAM_GAME_ROWS_EMPTY")
    for row in rows:
        if row["pass_plays"] <= 0 or row["rush_plays"] <= 0:
            raise NflGameScriptV2Error(
                f"TEAM_GAME_WORKLOAD_NONPOSITIVE:{row['game_id']}:{row['team']}"
            )
    return rows


def _validate_receipts(receipts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    found: dict[int, dict[str, Any]] = {}
    for raw in receipts:
        if not isinstance(raw, Mapping):
            raise NflGameScriptV2Error("SOURCE_RECEIPT_OBJECT_REQUIRED")
        season = _integer(raw.get("season"), "receipt.season")
        if season not in DEVELOPMENT_SEASONS:
            raise NflGameScriptV2Error(f"SOURCE_RECEIPT_OUTSIDE_V2_WINDOW:{season}")
        if season in found:
            raise NflGameScriptV2Error(f"SOURCE_RECEIPT_DUPLICATE:{season}")
        uri = str(raw.get("source_uri") or "").strip()
        if uri != expected_pbp_uri(season):
            raise NflGameScriptV2Error(f"SOURCE_URI_INVALID:{season}")
        digest = str(raw.get("raw_sha256") or "").strip().lower()
        if not _SHA256.fullmatch(digest):
            raise NflGameScriptV2Error(f"SOURCE_SHA256_INVALID:{season}")
        stamp = str(raw.get("retrieved_at") or "").strip()
        try:
            dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise NflGameScriptV2Error(f"SOURCE_RETRIEVED_AT_INVALID:{season}") from exc
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise NflGameScriptV2Error(f"SOURCE_RETRIEVED_AT_TIMEZONE_REQUIRED:{season}")
        found[season] = {
            "season": season,
            "source_uri": uri,
            "raw_sha256": digest,
            "retrieved_at": dt.isoformat(),
            "raw_bytes": int(raw.get("raw_bytes") or 0),
        }
    missing = sorted(set(DEVELOPMENT_SEASONS) - set(found))
    if missing:
        raise NflGameScriptV2Error(
            "SOURCE_RECEIPTS_MISSING:" + ",".join(str(x) for x in missing)
        )
    return [found[season] for season in DEVELOPMENT_SEASONS]


def _normalized_games(team_games: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, str], list[dict[str, Any]]] = {}
    seen: set[tuple[int, str, str]] = set()
    for raw in team_games:
        season = _development_season(raw.get("season"))
        game_id = str(raw.get("game_id") or "").strip()
        team = str(raw.get("team") or "").strip().upper()
        if not game_id or not team:
            raise NflGameScriptV2Error("TEAM_GAME_IDENTITY_REQUIRED")
        key = (season, game_id, team)
        if key in seen:
            raise NflGameScriptV2Error(f"TEAM_GAME_DUPLICATE:{season}:{game_id}:{team}")
        seen.add(key)
        row = {
            "season": season,
            "game_id": game_id,
            "team": team,
            "final_margin": _integer(raw.get("final_margin"), "final_margin"),
            "pass_plays": _integer(raw.get("pass_plays"), "pass_plays"),
            "rush_plays": _integer(raw.get("rush_plays"), "rush_plays"),
        }
        if row["pass_plays"] <= 0 or row["rush_plays"] <= 0:
            raise NflGameScriptV2Error("TEAM_GAME_WORKLOAD_POSITIVE_REQUIRED")
        grouped.setdefault((season, team), []).append(row)

    out: list[dict[str, Any]] = []
    for (season, team), rows in sorted(grouped.items()):
        if len(rows) < MIN_TEAM_SEASON_GAMES:
            continue
        pass_sum = sum(r["pass_plays"] for r in rows)
        rush_sum = sum(r["rush_plays"] for r in rows)
        other_n = len(rows) - 1
        for row in rows:
            pass_base = (pass_sum - row["pass_plays"]) / other_n
            rush_base = (rush_sum - row["rush_plays"]) / other_n
            if pass_base <= 0 or rush_base <= 0:
                raise NflGameScriptV2Error(
                    f"LEAVE_ONE_OUT_BASELINE_NONPOSITIVE:{season}:{team}"
                )
            out.append(
                {
                    **row,
                    "pass_ratio": row["pass_plays"] / pass_base,
                    "rush_ratio": row["rush_plays"] / rush_base,
                }
            )
    if not out:
        raise NflGameScriptV2Error("NO_TEAM_SEASONS_MEET_MINIMUM_GAMES")
    return sorted(out, key=lambda r: (r["season"], r["game_id"], r["team"]))


def margin_basis(margin: float) -> np.ndarray:
    x = float(margin)
    return np.asarray(
        [x, max(0.0, x + 14.0), max(0.0, x + 7.0), max(0.0, x),
         max(0.0, x - 7.0), max(0.0, x - 14.0)],
        dtype=float,
    )


def _design(rows: Sequence[Mapping[str, Any]]) -> np.ndarray:
    return np.vstack([margin_basis(float(row["final_margin"])) for row in rows])


def _fit_standardizer(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mean = np.mean(x, axis=0)
    scale = np.std(x, axis=0, ddof=0)
    scale = np.where(scale <= 1e-12, 1.0, scale)
    return mean, scale


def _ridge_fit(
    x: np.ndarray,
    y: np.ndarray,
    *,
    alpha: float,
    mean: np.ndarray,
    scale: np.ndarray,
) -> tuple[float, np.ndarray]:
    z = (x - mean) / scale
    y_mean = float(np.mean(y))
    centered = y - y_mean
    gram = z.T @ z + float(alpha) * np.eye(z.shape[1], dtype=float)
    coef = np.linalg.solve(gram, z.T @ centered)
    return y_mean, coef


def _predict(
    x: np.ndarray,
    *,
    intercept: float,
    coef: np.ndarray,
    mean: np.ndarray,
    scale: np.ndarray,
) -> np.ndarray:
    return float(intercept) + ((x - mean) / scale) @ coef


def _fit_targets(
    rows: Sequence[Mapping[str, Any]],
    *,
    alpha: float,
) -> dict[str, Any]:
    x = _design(rows)
    mean, scale = _fit_standardizer(x)
    out: dict[str, Any] = {
        "feature_mean": mean.tolist(),
        "feature_scale": scale.tolist(),
        "alpha": float(alpha),
    }
    for target in ("pass_ratio", "rush_ratio"):
        y = np.asarray([float(row[target]) for row in rows], dtype=float)
        intercept, coef = _ridge_fit(x, y, alpha=alpha, mean=mean, scale=scale)
        out[target] = {
            "intercept": intercept,
            "coef": coef.tolist(),
        }
    return out


def _predict_target(
    rows: Sequence[Mapping[str, Any]],
    model: Mapping[str, Any],
    target: str,
) -> np.ndarray:
    x = _design(rows)
    mean = np.asarray(model["feature_mean"], dtype=float)
    scale = np.asarray(model["feature_scale"], dtype=float)
    target_model = model[target]
    return _predict(
        x,
        intercept=float(target_model["intercept"]),
        coef=np.asarray(target_model["coef"], dtype=float),
        mean=mean,
        scale=scale,
    )


def select_alpha(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    seasons_present = sorted({int(row["season"]) for row in rows})
    if seasons_present != list(DEVELOPMENT_SEASONS):
        raise NflGameScriptV2Error("V2_CV_SEASONS_INCOMPLETE")

    candidates: list[dict[str, Any]] = []
    for alpha in ALPHAS:
        fold_rows: list[dict[str, Any]] = []
        for heldout in DEVELOPMENT_SEASONS:
            train = [row for row in rows if int(row["season"]) != heldout]
            test = [row for row in rows if int(row["season"]) == heldout]
            if not train or not test:
                raise NflGameScriptV2Error(f"V2_CV_FOLD_EMPTY:{heldout}")
            model = _fit_targets(train, alpha=alpha)
            pass_pred = _predict_target(test, model, "pass_ratio")
            rush_pred = _predict_target(test, model, "rush_ratio")
            pass_actual = np.asarray([float(row["pass_ratio"]) for row in test])
            rush_actual = np.asarray([float(row["rush_ratio"]) for row in test])
            pass_mae = float(np.mean(np.abs(pass_pred - pass_actual)))
            rush_mae = float(np.mean(np.abs(rush_pred - rush_actual)))
            fold_rows.append(
                {
                    "heldout_season": heldout,
                    "n_team_games": len(test),
                    "pass_ratio_mae": pass_mae,
                    "rush_ratio_mae": rush_mae,
                    "combined_mae": 0.5 * (pass_mae + rush_mae),
                }
            )
        weighted = sum(f["combined_mae"] * f["n_team_games"] for f in fold_rows) / sum(
            f["n_team_games"] for f in fold_rows
        )
        candidates.append(
            {
                "alpha": float(alpha),
                "weighted_combined_mae": float(weighted),
                "folds": fold_rows,
            }
        )

    # ALPHAS is predeclared in ascending order; exact metric ties therefore choose
    # the lower alpha deterministically without consulting validation data.
    winner = min(candidates, key=lambda row: (row["weighted_combined_mae"], row["alpha"]))
    return {
        "selected_alpha": winner["alpha"],
        "candidates": candidates,
    }


def _grid_diagnostic(model: Mapping[str, Any]) -> list[dict[str, float]]:
    mean = np.asarray(model["feature_mean"], dtype=float)
    scale = np.asarray(model["feature_scale"], dtype=float)
    rows: list[dict[str, float]] = []
    for margin in range(-35, 36):
        x = margin_basis(float(margin)).reshape(1, -1)
        p = float(
            _predict(
                x,
                intercept=float(model["pass_ratio"]["intercept"]),
                coef=np.asarray(model["pass_ratio"]["coef"], dtype=float),
                mean=mean,
                scale=scale,
            )[0]
        )
        r = float(
            _predict(
                x,
                intercept=float(model["rush_ratio"]["intercept"]),
                coef=np.asarray(model["rush_ratio"]["coef"], dtype=float),
                mean=mean,
                scale=scale,
            )[0]
        )
        rows.append({"margin": margin, "pass_multiplier": p, "rush_multiplier": r})
    return rows


def fit_game_script_v2(
    team_games: Sequence[Mapping[str, Any]],
    *,
    source_receipts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    prelock = load_prelock()
    receipts = _validate_receipts(source_receipts)
    rows = _normalized_games(team_games)
    selection = select_alpha(rows)
    model = _fit_targets(rows, alpha=float(selection["selected_alpha"]))
    grid = _grid_diagnostic(model)

    for point in grid:
        for key in ("pass_multiplier", "rush_multiplier"):
            value = float(point[key])
            if not MULTIPLIER_MIN <= value <= MULTIPLIER_MAX:
                raise NflGameScriptV2Error(
                    f"V2_FITTED_MULTIPLIER_OUT_OF_RANGE:{point['margin']}:{key}:{value}"
                )

    hash_rows = [
        {
            key: row[key]
            for key in ("season", "game_id", "team", "final_margin", "pass_plays", "rush_plays")
        }
        for row in rows
    ]
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "status": STATUS,
        "prelock_sha256": canonical_sha256(prelock),
        "fit_window": {
            "seasons": list(DEVELOPMENT_SEASONS),
            "season_type": "REG",
            "excluded_exposed_v1_seasons": list(EXPOSED_V1_SEASONS),
            "validation_season_accessed": False,
        },
        "source_receipts": receipts,
        "team_game_rows_sha256": canonical_sha256(hash_rows),
        "n_team_games": len(rows),
        "alpha_selection": selection,
        "model": model,
        "margin_grid_diagnostic": grid,
        "authority": {
            "research_only": True,
            "validated_2025": False,
            "changes_attempt9_owner": False,
            "creates_model_p": False,
            "truth_gate_authority": False,
            "official_authority": False,
            "promotion_authority": False,
            "staking_authority": False,
        },
    }
    payload["artifact_sha256"] = canonical_sha256(payload)
    return payload


def validate_artifact(artifact: Mapping[str, Any]) -> None:
    if artifact.get("schema") != SCHEMA:
        raise NflGameScriptV2Error("V2_ARTIFACT_SCHEMA_INVALID")
    if artifact.get("status") != STATUS:
        raise NflGameScriptV2Error("V2_ARTIFACT_STATUS_INVALID")
    expected = str(artifact.get("artifact_sha256") or "").lower()
    body = dict(artifact)
    body.pop("artifact_sha256", None)
    actual = canonical_sha256(body)
    if expected != actual:
        raise NflGameScriptV2Error(f"V2_ARTIFACT_SHA_MISMATCH:{actual}")


def script_multipliers(
    artifact: Mapping[str, Any],
    *,
    final_margin: float,
) -> dict[str, Any]:
    validate_artifact(artifact)
    x = margin_basis(float(final_margin)).reshape(1, -1)
    model = artifact["model"]
    mean = np.asarray(model["feature_mean"], dtype=float)
    scale = np.asarray(model["feature_scale"], dtype=float)
    out: dict[str, Any] = {
        "script_source": f"{SCHEMA}:{artifact['artifact_sha256']}",
        "final_margin": float(final_margin),
    }
    for target, output_key in (
        ("pass_ratio", "pass_multiplier"),
        ("rush_ratio", "rush_multiplier"),
    ):
        spec = model[target]
        value = float(
            _predict(
                x,
                intercept=float(spec["intercept"]),
                coef=np.asarray(spec["coef"], dtype=float),
                mean=mean,
                scale=scale,
            )[0]
        )
        if not MULTIPLIER_MIN <= value <= MULTIPLIER_MAX:
            raise NflGameScriptV2Error(
                f"V2_MULTIPLIER_OUT_OF_RANGE:{final_margin}:{output_key}:{value}"
            )
        out[output_key] = value
    return out


__all__ = [
    "ALPHAS",
    "DEVELOPMENT_SEASONS",
    "EXPOSED_V1_SEASONS",
    "KNOTS",
    "MODEL_FIELDS",
    "NflGameScriptV2Error",
    "VALIDATION_SEASON",
    "build_team_game_rows",
    "expected_pbp_uri",
    "fit_game_script_v2",
    "load_prelock",
    "margin_basis",
    "project_model_fields",
    "script_multipliers",
    "select_alpha",
    "validate_artifact",
]
