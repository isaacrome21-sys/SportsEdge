"""Development-only NFL prop usage V1 fitter.

The fitter is deliberately unable to accept 2025 rows. Hyperparameters, shrinkage
priors, residual scales, and baseline distributions are determined from 2021-2024
REG data only. Sportsbook lines/prices never enter this module.
"""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

FREEZE_PATH = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "research"
    / "nfl_prop_usage_v1_fit_freeze.json"
)
SCHEMA = "SPORTSEDGE_NFL_PROP_USAGE_V1_FIT_ARTIFACT"
STATUS = "FITTED_RESEARCH_ONLY_NOT_2025_VALIDATED"
DEV_SEASONS = (2021, 2022, 2023, 2024)
DECAY_ATTEMPT9 = 0.85
SCRIPT_REF = 22.5

MARKETS = {
    "passing_yards": {
        "positions": ("QB",),
        "usage": "attempts",
        "yards": "passing_yards",
    },
    "rushing_yards": {
        "positions": ("QB", "RB", "FB", "WR"),
        "usage": "carries",
        "yards": "rushing_yards",
    },
    "receiving_yards": {
        "positions": ("RB", "FB", "WR", "TE"),
        "usage": "targets",
        "yards": "receiving_yards",
    },
}
TEAM_ALIASES = {
    "LAR": "LA",
    "STL": "LA",
    "WSH": "WAS",
    "OAK": "LV",
    "SD": "LAC",
}

class NflPropUsageV1FitError(ValueError):
    pass


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return sha256(raw).hexdigest()


def load_freeze(path: Path | None = None) -> dict[str, Any]:
    cfg = json.loads((path or FREEZE_PATH).read_text())
    if cfg.get("schema") != "SPORTSEDGE_NFL_PROP_USAGE_V1_FIT_FREEZE":
        raise NflPropUsageV1FitError("PROP_V1_FIT_FREEZE_SCHEMA_INVALID")
    if cfg.get("status") != "FROZEN_BEFORE_2025_MODEL_SCORING":
        raise NflPropUsageV1FitError("PROP_V1_FIT_FREEZE_STATUS_INVALID")
    if tuple(cfg["development"]["seasons"]) != DEV_SEASONS:
        raise NflPropUsageV1FitError("PROP_V1_DEVELOPMENT_WINDOW_DRIFT")
    if int(cfg["validation"]["season"]) != 2025:
        raise NflPropUsageV1FitError("PROP_V1_VALIDATION_WINDOW_DRIFT")
    if cfg["validation"]["status"] != "UNTOUCHED":
        raise NflPropUsageV1FitError("PROP_V1_VALIDATION_ALREADY_TOUCHED")
    return cfg


def _team(value: Any) -> str:
    raw = str(value or "").strip().upper()
    return TEAM_ALIASES.get(raw, raw)


def _num(value: Any, field: str, *, default: float | None = None) -> float:
    if value in (None, ""):
        if default is not None:
            return float(default)
        raise NflPropUsageV1FitError(f"{field}:NUMERIC_REQUIRED")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise NflPropUsageV1FitError(f"{field}:NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise NflPropUsageV1FitError(f"{field}:NONFINITE")
    return out


def _int(value: Any, field: str) -> int:
    out = _num(value, field)
    if out != int(out):
        raise NflPropUsageV1FitError(f"{field}:INTEGER_REQUIRED")
    return int(out)


def _weighted(values: Sequence[float], decay: float) -> float:
    if not values:
        raise NflPropUsageV1FitError("WEIGHTED_VALUES_EMPTY")
    arr = np.asarray(values, dtype=float)
    weights = float(decay) ** np.arange(len(arr) - 1, -1, -1)
    return float(np.average(arr, weights=weights))


def _runtime_target(runtime: Mapping[str, Any], target: str, features: Sequence[float]) -> float:
    row = runtime["runtime"]["targets"][target]
    x = np.asarray(features, dtype=float)
    mean = np.asarray(row["feature_mean"], dtype=float)
    std = np.asarray(row["feature_std"], dtype=float)
    coef = np.asarray(row["coefficients"], dtype=float)
    if not (x.shape == mean.shape == std.shape == coef.shape):
        raise NflPropUsageV1FitError("ATTEMPT9_RUNTIME_DIMENSION_INVALID")
    return float(((x - mean) / std) @ coef + float(row["intercept"]))


def build_attempt9_team_environment(
    games: Sequence[Mapping[str, Any]],
    runtime: Mapping[str, Any],
    *,
    target_seasons: Sequence[int] = DEV_SEASONS,
) -> dict[tuple[int, int, str], float]:
    """Return market-blind Attempt-9 team scoring environment by season/week/team."""
    targets = set(int(x) for x in target_seasons)
    if 2025 in targets:
        raise NflPropUsageV1FitError("PROP_V1_FIT_CANNOT_BUILD_2025_ENVIRONMENT")

    normalized: list[dict[str, Any]] = []
    for raw in games:
        try:
            season = _int(raw.get("season"), "game.season")
            week = _int(raw.get("week"), "game.week")
        except NflPropUsageV1FitError:
            continue
        if str(raw.get("game_type") or "").upper() != "REG":
            continue
        home = _team(raw.get("home_team"))
        away = _team(raw.get("away_team"))
        if not home or not away:
            continue
        hs = raw.get("home_score")
        aw = raw.get("away_score")
        normalized.append({
            "season": season,
            "week": week,
            "date": str(raw.get("gameday") or ""),
            "id": str(raw.get("game_id") or f"{season}_{week}_{away}_{home}"),
            "home": home,
            "away": away,
            "hs": None if hs in (None, "") else _num(hs, "home_score"),
            "as": None if aw in (None, "") else _num(aw, "away_score"),
        })
    normalized.sort(key=lambda g: (g["date"], g["id"]))

    history: dict[str, list[tuple[float, float]]] = defaultdict(list)
    out: dict[tuple[int, int, str], float] = {}
    current_key: tuple[str, str] | None = None
    batch: list[dict[str, Any]] = []

    def flush(rows: list[dict[str, Any]]) -> None:
        for game in rows:
            if game["season"] in targets and len(history[game["home"]]) >= 5 and len(history[game["away"]]) >= 5:
                hp_hist = history[game["home"]][-10:]
                ap_hist = history[game["away"]][-10:]
                hp_for = _weighted([x[0] for x in hp_hist], DECAY_ATTEMPT9)
                hp_against = _weighted([x[1] for x in hp_hist], DECAY_ATTEMPT9)
                ap_for = _weighted([x[0] for x in ap_hist], DECAY_ATTEMPT9)
                ap_against = _weighted([x[1] for x in ap_hist], DECAY_ATTEMPT9)
                features = [
                    hp_for, hp_against, ap_for, ap_against,
                    hp_for - hp_against, ap_for - ap_against,
                ]
                margin = _runtime_target(runtime, "margin", features)
                total = _runtime_target(runtime, "total", features)
                out[(game["season"], game["week"], game["home"])] = (total + margin) / 2.0
                out[(game["season"], game["week"], game["away"])] = (total - margin) / 2.0
        for game in rows:
            if game["hs"] is None or game["as"] is None:
                continue
            history[game["home"]].append((game["hs"], game["as"]))
            history[game["away"]].append((game["as"], game["hs"]))

    for game in normalized:
        key = (game["date"], game["id"])
        if current_key is None:
            current_key = key
        if game["date"] != current_key[0]:
            flush(batch)
            batch = []
            current_key = key
        batch.append(game)
    if batch:
        flush(batch)
    return out


def normalize_player_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    required = {
        "season", "week", "season_type", "player_id", "position", "team",
        "attempts", "passing_yards", "carries", "rushing_yards", "targets", "receiving_yards",
    }
    for raw in rows:
        if not required.issubset(raw):
            missing = sorted(required - set(raw))
            raise NflPropUsageV1FitError("PLAYER_STATS_COLUMNS_MISSING:" + ",".join(missing))
        season = _int(raw.get("season"), "player.season")
        if season not in DEV_SEASONS:
            raise NflPropUsageV1FitError(f"PROP_V1_FIT_ROW_OUTSIDE_DEVELOPMENT:{season}")
        if str(raw.get("season_type") or "").upper() != "REG":
            continue
        pid = str(raw.get("player_id") or "").strip()
        pos = str(raw.get("position") or "").strip().upper()
        team = _team(raw.get("team"))
        if not pid or not pos or not team:
            continue
        out.append({
            "season": season,
            "week": _int(raw.get("week"), "player.week"),
            "player_id": pid,
            "player": str(raw.get("player_display_name") or raw.get("player_name") or pid).strip(),
            "position": pos,
            "team": team,
            "attempts": max(0.0, _num(raw.get("attempts"), "attempts", default=0.0)),
            "passing_yards": _num(raw.get("passing_yards"), "passing_yards", default=0.0),
            "carries": max(0.0, _num(raw.get("carries"), "carries", default=0.0)),
            "rushing_yards": _num(raw.get("rushing_yards"), "rushing_yards", default=0.0),
            "targets": max(0.0, _num(raw.get("targets"), "targets", default=0.0)),
            "receiving_yards": _num(raw.get("receiving_yards"), "receiving_yards", default=0.0),
        })
    return sorted(out, key=lambda r: (r["season"], r["week"], r["player_id"]))


def _efficiency_priors(
    rows: Sequence[Mapping[str, Any]],
    *,
    market: str,
    excluded_season: int | None,
) -> dict[str, float]:
    spec = MARKETS[market]
    acc: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for row in rows:
        if excluded_season is not None and int(row["season"]) == excluded_season:
            continue
        if row["position"] not in spec["positions"]:
            continue
        opp = float(row[spec["usage"]])
        yards = float(row[spec["yards"]])
        if opp > 0:
            acc[row["position"]][0] += yards
            acc[row["position"]][1] += opp
    priors = {pos: vals[0] / vals[1] for pos, vals in acc.items() if vals[1] > 0}
    if not priors:
        raise NflPropUsageV1FitError(f"EFFICIENCY_PRIORS_EMPTY:{market}")
    return priors


def _predict_market_rows(
    rows: Sequence[Mapping[str, Any]],
    env: Mapping[tuple[int, int, str], float],
    *,
    market: str,
    history_games: int,
    decay: float,
    prior_opportunities: float,
    gamma: float,
    excluded_prior_season: int | None,
    only_season: int | None,
) -> list[dict[str, Any]]:
    spec = MARKETS[market]
    priors = _efficiency_priors(rows, market=market, excluded_season=excluded_prior_season)
    histories: dict[tuple[int, str], list[Mapping[str, Any]]] = defaultdict(list)
    output: list[dict[str, Any]] = []
    for row in rows:
        season = int(row["season"])
        pid = str(row["player_id"])
        key = (season, pid)
        hist = histories[key]
        should_score = only_season is None or season == only_season
        if (
            should_score
            and row["position"] in spec["positions"]
            and len(hist) >= 3
            and (season, int(row["week"]), row["team"]) in env
        ):
            sample = hist[-int(history_games):]
            usage = _weighted([float(x[spec["usage"]]) for x in sample], decay)
            weights = float(decay) ** np.arange(len(sample) - 1, -1, -1)
            opp = np.asarray([float(x[spec["usage"]]) for x in sample], dtype=float)
            yards = np.asarray([float(x[spec["yards"]]) for x in sample], dtype=float)
            weighted_opp = float(np.sum(weights * opp))
            weighted_yards = float(np.sum(weights * yards))
            prior = priors.get(row["position"])
            if prior is not None:
                efficiency = (
                    weighted_yards + float(prior_opportunities) * float(prior)
                ) / (weighted_opp + float(prior_opportunities))
                team_points = float(env[(season, int(row["week"]), row["team"])])
                if team_points > 0:
                    script = (team_points / SCRIPT_REF) ** float(gamma)
                    pred = usage * efficiency * script
                    output.append({
                        "season": season,
                        "week": int(row["week"]),
                        "player_id": pid,
                        "position": row["position"],
                        "market": market,
                        "prediction": float(pred),
                        "actual": float(row[spec["yards"]]),
                        "usage": float(usage),
                        "efficiency": float(efficiency),
                        "attempt9_team_points": team_points,
                    })
        hist.append(row)
    return output


def _mae(rows: Sequence[Mapping[str, Any]]) -> float:
    if not rows:
        return float("inf")
    return float(np.mean([abs(float(r["prediction"]) - float(r["actual"])) for r in rows]))


def select_hyperparameters(
    rows: Sequence[Mapping[str, Any]],
    env: Mapping[tuple[int, int, str], float],
    freeze: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    search = freeze["hyperparameter_search"]
    selected: dict[str, dict[str, Any]] = {}
    diagnostics: dict[str, list[dict[str, Any]]] = {}
    for market in MARKETS:
        candidates: list[dict[str, Any]] = []
        for h in search["history_games"]:
            for d in search["decay"]:
                for prior_n in search["efficiency_prior_opportunities"]:
                    for gamma in search["script_gamma"]:
                        fold_rows: list[dict[str, Any]] = []
                        weighted_error = 0.0
                        n_total = 0
                        for heldout in DEV_SEASONS:
                            scored = _predict_market_rows(
                                rows, env, market=market,
                                history_games=int(h), decay=float(d),
                                prior_opportunities=float(prior_n), gamma=float(gamma),
                                excluded_prior_season=heldout, only_season=heldout,
                            )
                            n = len(scored)
                            fold_mae = _mae(scored)
                            fold_rows.append({"heldout_season": heldout, "n": n, "mae": fold_mae})
                            if n:
                                weighted_error += fold_mae * n
                                n_total += n
                        metric = weighted_error / n_total if n_total else float("inf")
                        candidates.append({
                            "history_games": int(h),
                            "decay": float(d),
                            "efficiency_prior_opportunities": float(prior_n),
                            "script_gamma": float(gamma),
                            "quantity_mae": float(metric),
                            "n_oof": int(n_total),
                            "folds": fold_rows,
                        })
        candidates.sort(key=lambda x: (
            x["quantity_mae"], x["history_games"], x["decay"],
            x["efficiency_prior_opportunities"], x["script_gamma"],
        ))
        if not candidates or not isfinite(candidates[0]["quantity_mae"]):
            raise NflPropUsageV1FitError(f"HYPERPARAMETER_SELECTION_EMPTY:{market}")
        selected[market] = {k: candidates[0][k] for k in (
            "history_games", "decay", "efficiency_prior_opportunities",
            "script_gamma", "quantity_mae", "n_oof",
        )}
        diagnostics[market] = candidates
    return selected, diagnostics


def _sample_sd(values: Sequence[float]) -> float:
    if len(values) < 2:
        raise NflPropUsageV1FitError("SIGMA_SAMPLE_TOO_SMALL")
    sd = float(np.std(np.asarray(values, dtype=float), ddof=1))
    if not isfinite(sd) or sd <= 0:
        raise NflPropUsageV1FitError("SIGMA_NONPOSITIVE")
    return sd


def fit_prop_usage_v1(
    player_rows: Sequence[Mapping[str, Any]],
    team_environment: Mapping[tuple[int, int, str], float],
    *,
    source_receipts: Mapping[str, Any],
    attempt9_artifact_sha256: str,
) -> dict[str, Any]:
    freeze = load_freeze()
    rows = normalize_player_rows(player_rows)
    if any(int(r["season"]) == 2025 for r in rows):
        raise NflPropUsageV1FitError("PROP_V1_FIT_2025_FORBIDDEN")

    selected, search_diag = select_hyperparameters(rows, team_environment, freeze)
    market_artifacts: dict[str, Any] = {}
    for market, params in selected.items():
        oof: list[dict[str, Any]] = []
        for heldout in DEV_SEASONS:
            oof.extend(_predict_market_rows(
                rows, team_environment, market=market,
                history_games=params["history_games"], decay=params["decay"],
                prior_opportunities=params["efficiency_prior_opportunities"],
                gamma=params["script_gamma"],
                excluded_prior_season=heldout, only_season=heldout,
            ))
        if not oof:
            raise NflPropUsageV1FitError(f"OOF_ROWS_EMPTY:{market}")
        pooled_sigma = _sample_sd([
            float(r["actual"]) - float(r["prediction"]) for r in oof
        ])
        position_sigma: dict[str, float] = {}
        for pos in MARKETS[market]["positions"]:
            vals = [
                float(r["actual"]) - float(r["prediction"])
                for r in oof if r["position"] == pos
            ]
            if len(vals) >= int(freeze["probability_layer"]["position_market_sigma_min_rows"]):
                position_sigma[pos] = _sample_sd(vals)

        priors = _efficiency_priors(rows, market=market, excluded_season=None)
        baseline: dict[str, Any] = {}
        for pos in MARKETS[market]["positions"]:
            vals = [
                float(r[MARKETS[market]["yards"]])
                for r in rows if r["position"] == pos
            ]
            if len(vals) >= 2:
                baseline[pos] = {
                    "n": len(vals),
                    "mean": float(np.mean(vals)),
                    "sd": _sample_sd(vals),
                }

        market_artifacts[market] = {
            "selected": params,
            "efficiency_prior_by_position": priors,
            "oof_n": len(oof),
            "oof_residual_sigma_pooled": pooled_sigma,
            "oof_residual_sigma_by_position": position_sigma,
            "baseline_actual_distribution_by_position": baseline,
            "oof_rows_sha256": canonical_sha256(oof),
            "search_sha256": canonical_sha256(search_diag[market]),
        }

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "status": STATUS,
        "freeze_sha256": canonical_sha256(freeze),
        "development_seasons": list(DEV_SEASONS),
        "validation_season_accessed": False,
        "attempt9_artifact_sha256": str(attempt9_artifact_sha256),
        "source_receipts": dict(source_receipts),
        "markets": market_artifacts,
        "authority": {
            "research_only": True,
            "creates_model_p": False,
            "truth_gate": False,
            "official": False,
            "promotion": False,
            "staking": False,
            "backfill": False,
        },
    }
    payload["artifact_sha256"] = canonical_sha256(payload)
    return payload


def validate_artifact(artifact: Mapping[str, Any]) -> None:
    if artifact.get("schema") != SCHEMA or artifact.get("status") != STATUS:
        raise NflPropUsageV1FitError("PROP_V1_ARTIFACT_IDENTITY_INVALID")
    if artifact.get("validation_season_accessed") is not False:
        raise NflPropUsageV1FitError("PROP_V1_ARTIFACT_2025_ACCESS_INVALID")
    expected = str(artifact.get("artifact_sha256") or "")
    body = dict(artifact)
    body.pop("artifact_sha256", None)
    actual = canonical_sha256(body)
    if expected != actual:
        raise NflPropUsageV1FitError(f"PROP_V1_ARTIFACT_SHA_MISMATCH:{actual}")


__all__ = [
    "DEV_SEASONS", "MARKETS", "NflPropUsageV1FitError",
    "build_attempt9_team_environment", "fit_prop_usage_v1", "load_freeze",
    "normalize_player_rows", "select_hyperparameters", "validate_artifact",
]
