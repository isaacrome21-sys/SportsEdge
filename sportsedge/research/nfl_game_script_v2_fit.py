"""Frozen NFL game-script V2 research fitter.

V2 is a fresh-window successor to failed V1. It fits smooth market-blind
pass/rush workload multipliers from 2011-2015 nflverse PBP only. The exposed
2016-2024 V1 fit window and clean 2025 validation season are inaccessible to
this module's fit contract.
"""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
from typing import Any, Mapping, Sequence

PRELOCK_PATH = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "research"
    / "nfl_game_script_v2_prelock.json"
)

SCHEMA = "SPORTSEDGE_NFL_GAME_SCRIPT_V2_ARTIFACT"
STATUS = "FITTED_RESEARCH_ONLY_NOT_VALIDATED"
FIT_SEASONS = (2011, 2012, 2013, 2014, 2015)
EXPOSED_V1_SEASONS = tuple(range(2016, 2025))
VALIDATION_SEASON = 2025
MIN_TEAM_SEASON_GAMES = 8
ALPHAS = (0.1, 1.0, 10.0, 100.0)
KNOTS = (-14.0, -7.0, 0.0, 7.0, 14.0)
MULTIPLIER_MIN = 0.4
MULTIPLIER_MAX = 1.8

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
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return sha256(raw).hexdigest()


def load_prelock(path: Path | None = None) -> dict[str, Any]:
    cfg = json.loads((path or PRELOCK_PATH).read_text())
    if cfg.get("schema") != "SPORTSEDGE_NFL_GAME_SCRIPT_V2_PRELOCK":
        raise NflGameScriptV2Error("GAME_SCRIPT_V2_PRELOCK_SCHEMA_INVALID")
    if cfg.get("status") != "FROZEN_BEFORE_V2_SCORING":
        raise NflGameScriptV2Error("GAME_SCRIPT_V2_PRELOCK_STATUS_INVALID")
    if tuple(int(x) for x in cfg["fit_window"]["seasons"]) != FIT_SEASONS:
        raise NflGameScriptV2Error("GAME_SCRIPT_V2_FIT_WINDOW_DRIFT")
    if tuple(int(x) for x in cfg["excluded_from_v2_fit_or_selection"]["seasons"]) != EXPOSED_V1_SEASONS:
        raise NflGameScriptV2Error("GAME_SCRIPT_V2_EXPOSED_WINDOW_DRIFT")
    if int(cfg["validation_window"]["season"]) != VALIDATION_SEASON:
        raise NflGameScriptV2Error("GAME_SCRIPT_V2_VALIDATION_WINDOW_DRIFT")
    if cfg["model"].get("alpha_tie_break") != "SMALLEST_ALPHA":
        raise NflGameScriptV2Error("GAME_SCRIPT_V2_ALPHA_TIE_BREAK_DRIFT")
    return cfg


def expected_pbp_uri(season: int) -> str:
    season = int(season)
    if season not in FIT_SEASONS:
        raise NflGameScriptV2Error(f"FIT_SOURCE_SEASON_FORBIDDEN:{season}")
    return (
        "https://github.com/nflverse/nflverse-data/releases/download/pbp/"
        f"play_by_play_{season}.csv"
    )


def _num(value: Any, field: str) -> float:
    if value in (None, "") or isinstance(value, bool):
        raise NflGameScriptV2Error(f"{field}:NUMERIC_REQUIRED")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise NflGameScriptV2Error(f"{field}:NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise NflGameScriptV2Error(f"{field}:NONFINITE")
    return out


def _int(value: Any, field: str) -> int:
    out = _num(value, field)
    if out != int(out):
        raise NflGameScriptV2Error(f"{field}:INTEGER_REQUIRED")
    return int(out)


def _binary(value: Any, field: str) -> int:
    if value in (None, ""):
        return 0
    out = _int(value, field)
    if out not in (0, 1):
        raise NflGameScriptV2Error(f"{field}:BINARY_REQUIRED")
    return out


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
    home = _int(row.get("home_score"), "home_score")
    away = _int(row.get("away_score"), "away_score")
    side = str(row.get("posteam_type") or "").strip().lower()
    if side == "home":
        return home - away
    if side == "away":
        return away - home
    raise NflGameScriptV2Error("POSTEAM_TYPE_HOME_AWAY_REQUIRED")


def build_team_game_rows(pbp_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, str, str], dict[str, Any]] = {}
    for raw in pbp_rows:
        row = project_model_fields(raw)
        if str(row.get("season_type") or "").strip().upper() != "REG":
            continue
        season = _int(row.get("season"), "season")
        if season not in FIT_SEASONS:
            raise NflGameScriptV2Error(f"FIT_ROW_OUTSIDE_FRESH_WINDOW:{season}")
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
            raise NflGameScriptV2Error(f"FINAL_MARGIN_INCONSISTENT:{game_id}:{team}")
        current["pass_plays" if kind == "PASS" else "rush_plays"] += 1

    rows = sorted(grouped.values(), key=lambda r: (r["season"], r["game_id"], r["team"]))
    if not rows:
        raise NflGameScriptV2Error("TEAM_GAME_ROWS_EMPTY")
    return rows


def _normalized_games(team_games: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[int, str, str]] = set()
    for raw in team_games:
        season = _int(raw.get("season"), "season")
        if season not in FIT_SEASONS:
            raise NflGameScriptV2Error(f"FIT_ROW_OUTSIDE_FRESH_WINDOW:{season}")
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
            "final_margin": _int(raw.get("final_margin"), "final_margin"),
            "pass_plays": _int(raw.get("pass_plays"), "pass_plays"),
            "rush_plays": _int(raw.get("rush_plays"), "rush_plays"),
        }
        if row["pass_plays"] <= 0 or row["rush_plays"] <= 0:
            continue
        groups[(season, team)].append(row)

    out: list[dict[str, Any]] = []
    for (season, team), rows in sorted(groups.items()):
        if len(rows) < MIN_TEAM_SEASON_GAMES:
            continue
        pass_sum = sum(r["pass_plays"] for r in rows)
        rush_sum = sum(r["rush_plays"] for r in rows)
        denom = len(rows) - 1
        for row in rows:
            pass_base = (pass_sum - row["pass_plays"]) / denom
            rush_base = (rush_sum - row["rush_plays"]) / denom
            if pass_base <= 0 or rush_base <= 0:
                raise NflGameScriptV2Error(f"LOO_BASELINE_NONPOSITIVE:{season}:{team}")
            out.append({
                **row,
                "pass_ratio": row["pass_plays"] / pass_base,
                "rush_ratio": row["rush_plays"] / rush_base,
            })
    if not out:
        raise NflGameScriptV2Error("NO_TEAM_SEASONS_MEET_MINIMUM_GAMES")
    return sorted(out, key=lambda r: (r["season"], r["game_id"], r["team"]))


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


def _fit_standardizer(xs: Sequence[Sequence[float]]) -> tuple[list[float], list[float]]:
    if not xs:
        raise NflGameScriptV2Error("STANDARDIZER_EMPTY")
    width = len(xs[0])
    means = [0.0] * width
    scales = [1.0] * width
    means[0] = 0.0
    for j in range(1, width):
        values = [row[j] for row in xs]
        mean = sum(values) / len(values)
        var = sum((v - mean) ** 2 for v in values) / len(values)
        means[j] = mean
        scales[j] = var ** 0.5 if var > 1e-18 else 1.0
    return means, scales


def _standardize(row: Sequence[float], means: Sequence[float], scales: Sequence[float]) -> list[float]:
    out = [1.0]
    out.extend((row[j] - means[j]) / scales[j] for j in range(1, len(row)))
    return out


def _solve_linear(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    mat = [list(a[i]) + [b[i]] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(mat[r][col]))
        if abs(mat[pivot][col]) < 1e-12:
            raise NflGameScriptV2Error("RIDGE_SYSTEM_SINGULAR")
        mat[col], mat[pivot] = mat[pivot], mat[col]
        p = mat[col][col]
        mat[col] = [v / p for v in mat[col]]
        for r in range(n):
            if r == col:
                continue
            factor = mat[r][col]
            if factor == 0.0:
                continue
            mat[r] = [mat[r][c] - factor * mat[col][c] for c in range(n + 1)]
    return [mat[i][-1] for i in range(n)]


def _ridge_fit(xs: Sequence[Sequence[float]], ys: Sequence[float], alpha: float) -> dict[str, Any]:
    if len(xs) != len(ys) or not xs:
        raise NflGameScriptV2Error("RIDGE_INPUT_INVALID")
    raw = [_basis(row[0]) if len(row) == 1 else list(row) for row in xs]
    means, scales = _fit_standardizer(raw)
    z = [_standardize(row, means, scales) for row in raw]
    p = len(z[0])
    xtx = [[0.0] * p for _ in range(p)]
    xty = [0.0] * p
    for row, y in zip(z, ys):
        for j in range(p):
            xty[j] += row[j] * y
            for k in range(p):
                xtx[j][k] += row[j] * row[k]
    for j in range(1, p):
        xtx[j][j] += float(alpha)
    coef = _solve_linear(xtx, xty)
    return {"coef": coef, "means": means, "scales": scales, "alpha": float(alpha)}


def _predict(model: Mapping[str, Any], margin: float) -> float:
    raw = _basis(float(margin))
    z = _standardize(raw, model["means"], model["scales"])
    return sum(float(c) * float(x) for c, x in zip(model["coef"], z))


def _mae(actual: Sequence[float], predicted: Sequence[float]) -> float:
    if len(actual) != len(predicted) or not actual:
        raise NflGameScriptV2Error("MAE_INPUT_INVALID")
    return sum(abs(a - p) for a, p in zip(actual, predicted)) / len(actual)


def _cv_score(rows: Sequence[Mapping[str, Any]], alpha: float) -> dict[str, float]:
    pass_actual: list[float] = []
    pass_pred: list[float] = []
    rush_actual: list[float] = []
    rush_pred: list[float] = []
    for holdout in FIT_SEASONS:
        train = [r for r in rows if int(r["season"]) != holdout]
        test = [r for r in rows if int(r["season"]) == holdout]
        if not train or not test:
            raise NflGameScriptV2Error(f"CV_FOLD_EMPTY:{holdout}")
        x_train = [[float(r["final_margin"])] for r in train]
        pass_model = _ridge_fit(x_train, [float(r["pass_ratio"]) for r in train], alpha)
        rush_model = _ridge_fit(x_train, [float(r["rush_ratio"]) for r in train], alpha)
        for row in test:
            m = float(row["final_margin"])
            pass_actual.append(float(row["pass_ratio"]))
            pass_pred.append(_predict(pass_model, m))
            rush_actual.append(float(row["rush_ratio"]))
            rush_pred.append(_predict(rush_model, m))
    p_mae = _mae(pass_actual, pass_pred)
    r_mae = _mae(rush_actual, rush_pred)
    return {
        "pass_ratio_mae": p_mae,
        "rush_ratio_mae": r_mae,
        "selection_metric": 0.5 * (p_mae + r_mae),
    }


def fit_game_script_v2(
    team_games: Sequence[Mapping[str, Any]],
    *,
    source_receipts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    prelock = load_prelock()
    rows = _normalized_games(team_games)

    receipt_map: dict[int, dict[str, Any]] = {}
    for raw in source_receipts:
        season = _int(raw.get("season"), "receipt.season")
        if season not in FIT_SEASONS:
            raise NflGameScriptV2Error(f"FIT_SOURCE_SEASON_FORBIDDEN:{season}")
        if season in receipt_map:
            raise NflGameScriptV2Error(f"SOURCE_RECEIPT_DUPLICATE:{season}")
        uri = str(raw.get("source_uri") or "")
        if uri != expected_pbp_uri(season):
            raise NflGameScriptV2Error(f"SOURCE_URI_INVALID:{season}")
        digest = str(raw.get("raw_sha256") or "").lower()
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise NflGameScriptV2Error(f"SOURCE_SHA256_INVALID:{season}")
        stamp = str(raw.get("retrieved_at") or "").strip()
        if not stamp:
            raise NflGameScriptV2Error(f"SOURCE_RETRIEVED_AT_REQUIRED:{season}")
        receipt_map[season] = {
            "season": season,
            "source_uri": uri,
            "raw_sha256": digest,
            "retrieved_at": stamp,
            "raw_bytes": int(raw.get("raw_bytes") or 0),
        }
    missing = [s for s in FIT_SEASONS if s not in receipt_map]
    if missing:
        raise NflGameScriptV2Error("SOURCE_RECEIPTS_MISSING:" + ",".join(map(str, missing)))

    cv = []
    for alpha in ALPHAS:
        metrics = _cv_score(rows, alpha)
        cv.append({"alpha": alpha, **metrics})
    winner = min(cv, key=lambda r: (r["selection_metric"], r["alpha"]))
    chosen = float(winner["alpha"])

    x_all = [[float(r["final_margin"])] for r in rows]
    pass_model = _ridge_fit(x_all, [float(r["pass_ratio"]) for r in rows], chosen)
    rush_model = _ridge_fit(x_all, [float(r["rush_ratio"]) for r in rows], chosen)

    probe_margins = list(range(-35, 36))
    probe = []
    for margin in probe_margins:
        p = _predict(pass_model, margin)
        r = _predict(rush_model, margin)
        if not (MULTIPLIER_MIN <= p <= MULTIPLIER_MAX):
            raise NflGameScriptV2Error(f"PASS_MULTIPLIER_OUT_OF_RANGE:{margin}:{p}")
        if not (MULTIPLIER_MIN <= r <= MULTIPLIER_MAX):
            raise NflGameScriptV2Error(f"RUSH_MULTIPLIER_OUT_OF_RANGE:{margin}:{r}")
        probe.append({"margin": margin, "pass_multiplier": p, "rush_multiplier": r})

    hash_rows = [
        {k: row[k] for k in ("season","game_id","team","final_margin","pass_plays","rush_plays")}
        for row in rows
    ]
    artifact: dict[str, Any] = {
        "schema": SCHEMA,
        "status": STATUS,
        "prelock_sha256": canonical_sha256(prelock),
        "fit_window": {"seasons": list(FIT_SEASONS), "season_type": "REG"},
        "excluded_v1_window": list(EXPOSED_V1_SEASONS),
        "validation_season_accessed": False,
        "source_receipts": [receipt_map[s] for s in FIT_SEASONS],
        "n_team_games": len(rows),
        "team_game_rows_sha256": canonical_sha256(hash_rows),
        "cv": {
            "folds": list(FIT_SEASONS),
            "alpha_grid": list(ALPHAS),
            "alpha_tie_break": "SMALLEST_ALPHA",
            "rows": cv,
            "selected_alpha": chosen,
        },
        "pass_model": pass_model,
        "rush_model": rush_model,
        "probe_minus35_to_plus35": probe,
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
    artifact["artifact_sha256"] = canonical_sha256(artifact)
    return artifact


def validate_artifact(artifact: Mapping[str, Any]) -> None:
    if artifact.get("schema") != SCHEMA or artifact.get("status") != STATUS:
        raise NflGameScriptV2Error("GAME_SCRIPT_V2_ARTIFACT_IDENTITY_INVALID")
    if artifact.get("validation_season_accessed") is not False:
        raise NflGameScriptV2Error("GAME_SCRIPT_V2_VALIDATION_ACCESS_INVALID")
    expected = str(artifact.get("artifact_sha256") or "")
    body = dict(artifact)
    body.pop("artifact_sha256", None)
    if canonical_sha256(body) != expected:
        raise NflGameScriptV2Error("GAME_SCRIPT_V2_ARTIFACT_SHA_MISMATCH")


def script_multipliers(artifact: Mapping[str, Any], *, final_margin: float) -> dict[str, Any]:
    validate_artifact(artifact)
    margin = float(final_margin)
    p = _predict(artifact["pass_model"], margin)
    r = _predict(artifact["rush_model"], margin)
    if not (MULTIPLIER_MIN <= p <= MULTIPLIER_MAX and MULTIPLIER_MIN <= r <= MULTIPLIER_MAX):
        raise NflGameScriptV2Error(f"GAME_SCRIPT_V2_RUNTIME_OUT_OF_RANGE:{margin}")
    return {
        "pass_multiplier": p,
        "rush_multiplier": r,
        "script_source": f"{SCHEMA}:{artifact['artifact_sha256']}",
    }


__all__ = [
    "ALPHAS",
    "EXPOSED_V1_SEASONS",
    "FIT_SEASONS",
    "MODEL_FIELDS",
    "NflGameScriptV2Error",
    "VALIDATION_SEASON",
    "build_team_game_rows",
    "expected_pbp_uri",
    "fit_game_script_v2",
    "load_prelock",
    "project_model_fields",
    "script_multipliers",
    "validate_artifact",
]
