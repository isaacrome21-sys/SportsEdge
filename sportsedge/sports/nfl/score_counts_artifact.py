"""Deterministic fit artifact and forward-prediction records for NFL_SCORE_COUNTS_G1.

This module contains no network acquisition and no sportsbook binding. Historical
development fitting and pregame forward prediction must be invoked only by a
separately frozen governed runner.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import exp, isfinite
from typing import Any, Mapping, Sequence

import numpy as np

from sportsedge.sports.nfl.score_counts_g1 import (
    ALPHA_GRID,
    FEATURE_NAMES,
    FG_ATTEMPT2_ALPHA_GRID,
    FG_ATTEMPT2_FEATURE_NAMES,
    ROOT_SEED_LITERAL,
    ROOT_SEED_UINT64,
    SIGMA_GRID,
    PoissonRidge,
    ScoreCountFit,
    ScoreCountsError,
    choose_alpha,
    fit_core,
    fit_poisson_ridge,
    predict_mean,
    simulate_game,
)

FIT_SCHEMA = "SPORTSEDGE_NFL_SCORE_COUNTS_G1_ATTEMPT_FIT_V1"
PREDICTION_SCHEMA = "SPORTSEDGE_NFL_SCORE_COUNTS_G1_FORWARD_PREDICTION_V1"
DEVELOPMENT_SEASONS = tuple(range(2018, 2026))
SIGMA_VALIDATION_SEASONS = (2021, 2022, 2023, 2024, 2025)
FORWARD_SEASON = 2026
FORWARD_FIRST_WEEK = 5
FORWARD_FIRST_KICKOFF = "2026-10-09T00:15:00Z"
FORBIDDEN_FORWARD_FIELDS = {
    "offense_touchdowns", "made_field_goals", "def_st_touchdowns", "safeties",
    "pat_made", "two_point_made", "no_conversion", "home_score", "away_score",
    "spread_line", "total_line", "odds", "price", "result", "outcome",
}


class ScoreCountArtifactError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _digest(value: Any) -> str:
    return sha256(_canonical(value)).hexdigest()


def _sha(value: Any, field: str) -> str:
    raw = str(value or "").strip().lower()
    if len(raw) != 64 or any(ch not in "0123456789abcdef" for ch in raw):
        raise ScoreCountArtifactError(f"{field}:SHA256_REQUIRED")
    return raw


def _utc(value: Any, field: str) -> datetime:
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value or "").strip().replace("Z", "+00:00")
        )
    except (TypeError, ValueError) as exc:
        raise ScoreCountArtifactError(f"{field}:TIMESTAMP_REQUIRED") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ScoreCountArtifactError(f"{field}:TIMEZONE_REQUIRED")
    return dt.astimezone(timezone.utc)


def _finite(value: Any, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ScoreCountArtifactError(f"{field}:NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise ScoreCountArtifactError(f"{field}:FINITE_REQUIRED")
    return out


def _poisson_dict(model: PoissonRidge) -> dict[str, Any]:
    return {
        "target": model.target,
        "alpha": model.alpha,
        "feature_names": list(model.feature_names),
        "mean": list(model.mean),
        "scale": list(model.scale),
        "intercept": model.intercept,
        "coefficients": list(model.coefficients),
    }


def _poisson_from_dict(
    value: Mapping[str, Any],
    *,
    expected_feature_names: Sequence[str] = FEATURE_NAMES,
) -> PoissonRidge:
    names = tuple(str(x) for x in value.get("feature_names") or ())
    expected_names = tuple(str(x) for x in expected_feature_names)
    if names != expected_names:
        raise ScoreCountArtifactError("FIT_FEATURE_IDENTITY_MISMATCH")
    mean = tuple(float(x) for x in value.get("mean") or ())
    scale = tuple(float(x) for x in value.get("scale") or ())
    coef = tuple(float(x) for x in value.get("coefficients") or ())
    if not (len(mean) == len(scale) == len(coef) == len(expected_names)):
        raise ScoreCountArtifactError("FIT_VECTOR_LENGTH_MISMATCH")
    if any((not isfinite(v)) for v in (*mean, *scale, *coef)):
        raise ScoreCountArtifactError("FIT_VECTOR_NONFINITE")
    if any(v <= 0 for v in scale):
        raise ScoreCountArtifactError("FIT_SCALE_NONPOSITIVE")
    return PoissonRidge(
        target=str(value.get("target") or ""),
        alpha=float(value["alpha"]),
        feature_names=names,
        mean=mean,
        scale=scale,
        intercept=float(value["intercept"]),
        coefficients=coef,
    )


def fit_from_artifact(artifact: Mapping[str, Any]) -> ScoreCountFit:
    if artifact.get("schema") != FIT_SCHEMA:
        raise ScoreCountArtifactError("FIT_SCHEMA_INVALID")
    expected = str(artifact.get("artifact_sha256") or "")
    check = dict(artifact)
    check.pop("artifact_sha256", None)
    if _digest(check) != expected:
        raise ScoreCountArtifactError("FIT_ARTIFACT_DIGEST_MISMATCH")
    fit = artifact.get("fit")
    if not isinstance(fit, Mapping):
        raise ScoreCountArtifactError("FIT_OBJECT_REQUIRED")
    probs = tuple(float(v) for v in fit.get("conversion_probabilities") or ())
    if len(probs) != 3 or abs(sum(probs) - 1.0) > 1e-9:
        raise ScoreCountArtifactError("FIT_CONVERSION_PROBABILITIES_INVALID")
    attempt_number = int(artifact.get("attempt_number", 1))
    fg_feature_names = (
        FG_ATTEMPT2_FEATURE_NAMES if attempt_number == 2 else FEATURE_NAMES
    )
    return ScoreCountFit(
        td_model=_poisson_from_dict(
            fit["td_model"], expected_feature_names=FEATURE_NAMES
        ),
        fg_model=_poisson_from_dict(
            fit["fg_model"], expected_feature_names=fg_feature_names
        ),
        shared_sigma=float(fit["shared_sigma"]),
        def_st_td_rate=float(fit["def_st_td_rate"]),
        safety_rate=float(fit["safety_rate"]),
        conversion_probabilities=probs,
        source_manifest_sha256=_sha(fit.get("source_manifest_sha256"), "source_manifest_sha256"),
        code_identity=str(fit.get("code_identity") or ""),
    )


def _game_pairs(rows: Sequence[Mapping[str, Any]]) -> dict[str, tuple[Mapping[str, Any], Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("game_id") or "")].append(row)
    out: dict[str, tuple[Mapping[str, Any], Mapping[str, Any]]] = {}
    for gid, pair in grouped.items():
        if not gid or len(pair) != 2:
            raise ScoreCountArtifactError(f"GAME_PAIR_REQUIRED:{gid}:{len(pair)}")
        home = [row for row in pair if abs(_finite(row.get("home_indicator"), "home_indicator") - 1.0) < 1e-12]
        away = [row for row in pair if abs(_finite(row.get("home_indicator"), "home_indicator")) < 1e-12]
        if len(home) != 1 or len(away) != 1:
            raise ScoreCountArtifactError(f"HOME_AWAY_PAIR_REQUIRED:{gid}")
        out[gid] = (home[0], away[0])
    return out


def _poisson_deviance(y: np.ndarray, mu: np.ndarray) -> float:
    if y.size == 0 or y.shape != mu.shape:
        raise ScoreCountArtifactError("DEVELOPMENT_DEVIANCE_SHAPE")
    safe_mu = np.clip(mu.astype(float), 1e-12, None)
    term = np.where(y > 0, y * np.log(y / safe_mu) - (y - safe_mu), safe_mu)
    return float(2.0 * np.mean(term))


def _attempt_fg_spec(attempt_number: int) -> tuple[tuple[str, ...], tuple[float, ...]]:
    attempt = int(attempt_number)
    if attempt == 2:
        return FG_ATTEMPT2_FEATURE_NAMES, FG_ATTEMPT2_ALPHA_GRID
    return FEATURE_NAMES, ALPHA_GRID


def _development_count_gate(
    rows: Sequence[Mapping[str, Any]],
    *,
    attempt_number: int,
) -> dict[str, Any]:
    """Frozen historical gate; Attempt 2 changes only the FG mean specification."""
    target_results: dict[str, Any] = {}
    all_pass = True
    for target in ("offense_touchdowns", "made_field_goals"):
        folds = []
        pooled_y: list[float] = []
        pooled_candidate: list[float] = []
        pooled_baseline: list[float] = []
        wins = 0
        for validation_season in SIGMA_VALIDATION_SEASONS:
            train = [row for row in rows if int(row["season"]) < validation_season]
            valid = [row for row in rows if int(row["season"]) == validation_season]
            train_seasons = sorted({int(row["season"]) for row in train})
            if len(train_seasons) < 3 or not valid:
                raise ScoreCountArtifactError(f"DEVELOPMENT_GATE_FOLD_INCOMPLETE:{target}:{validation_season}")
            feature_names, alpha_grid = (
                _attempt_fg_spec(attempt_number)
                if target == "made_field_goals"
                else (FEATURE_NAMES, ALPHA_GRID)
            )
            alpha, _ = choose_alpha(
                train,
                target=target,
                alphas=alpha_grid,
                feature_names=feature_names,
            )
            model = fit_poisson_ridge(
                train,
                target=target,
                alpha=alpha,
                feature_names=feature_names,
            )
            y = np.asarray([_finite(row.get(target), target) for row in valid], dtype=float)
            candidate = np.asarray([predict_mean(model, row) for row in valid], dtype=float)
            train_y = np.asarray([_finite(row.get(target), target) for row in train], dtype=float)
            baseline_mean = max(float(np.mean(train_y)), 1e-12)
            baseline = np.full_like(y, baseline_mean, dtype=float)
            candidate_dev = _poisson_deviance(y, candidate)
            baseline_dev = _poisson_deviance(y, baseline)
            won = candidate_dev < baseline_dev
            wins += int(won)
            folds.append({
                "validation_season": validation_season,
                "training_seasons": train_seasons,
                "n_team_rows": len(valid),
                "selected_alpha": alpha,
                "feature_names": list(feature_names),
                "candidate_poisson_deviance": candidate_dev,
                "intercept_baseline_poisson_deviance": baseline_dev,
                "fold_win": won,
            })
            pooled_y.extend(float(v) for v in y)
            pooled_candidate.extend(float(v) for v in candidate)
            pooled_baseline.extend(float(v) for v in baseline)

        y_all = np.asarray(pooled_y, dtype=float)
        candidate_all = np.asarray(pooled_candidate, dtype=float)
        baseline_all = np.asarray(pooled_baseline, dtype=float)
        candidate_dev = _poisson_deviance(y_all, candidate_all)
        baseline_dev = _poisson_deviance(y_all, baseline_all)
        passed = bool(candidate_dev < baseline_dev and wins >= 3)
        all_pass = all_pass and passed
        target_results[target] = {
            "pooled_candidate_poisson_deviance": candidate_dev,
            "pooled_intercept_baseline_poisson_deviance": baseline_dev,
            "pooled_improvement": baseline_dev - candidate_dev,
            "fold_wins": wins,
            "folds_total": len(SIGMA_VALIDATION_SEASONS),
            "minimum_fold_wins": 3,
            "pass": passed,
            "folds": folds,
        }
    return {
        "schema": "SPORTSEDGE_NFL_SCORE_COUNTS_G1_DEVELOPMENT_GATE_V1",
        "validation_seasons": list(SIGMA_VALIDATION_SEASONS),
        "baseline": "TRAINING_FOLD_INTERCEPT_ONLY_POISSON_MEAN",
        "all_targets_must_pass": True,
        "targets": target_results,
        "pass": bool(all_pass),
        "market_data_used": False,
    }


def _select_shared_sigma(
    rows: Sequence[Mapping[str, Any]],
    *,
    attempt_number: int,
) -> tuple[float, dict[str, Any]]:
    seasons = sorted({int(row["season"]) for row in rows})
    if seasons != list(DEVELOPMENT_SEASONS):
        raise ScoreCountArtifactError(f"DEVELOPMENT_SEASONS_EXACT_REQUIRED:{seasons}")
    residual_rows: list[dict[str, float | int | str]] = []
    fold_meta: list[dict[str, Any]] = []
    for validation_season in SIGMA_VALIDATION_SEASONS:
        train = [row for row in rows if int(row["season"]) < validation_season]
        valid = [row for row in rows if int(row["season"]) == validation_season]
        train_seasons = sorted({int(row["season"]) for row in train})
        if len(train_seasons) < 3 or not valid:
            raise ScoreCountArtifactError(f"SIGMA_FOLD_INCOMPLETE:{validation_season}")
        td_alpha, td_cv = choose_alpha(
            train, target="offense_touchdowns", alphas=ALPHA_GRID
        )
        fg_feature_names, fg_alpha_grid = _attempt_fg_spec(attempt_number)
        fg_alpha, fg_cv = choose_alpha(
            train,
            target="made_field_goals",
            alphas=fg_alpha_grid,
            feature_names=fg_feature_names,
        )
        td = fit_poisson_ridge(
            train, target="offense_touchdowns", alpha=td_alpha
        )
        fg = fit_poisson_ridge(
            train,
            target="made_field_goals",
            alpha=fg_alpha,
            feature_names=fg_feature_names,
        )
        pairs = _game_pairs(valid)
        for gid, (home, away) in sorted(pairs.items()):
            h_mu = predict_mean(td, home) + predict_mean(fg, home)
            a_mu = predict_mean(td, away) + predict_mean(fg, away)
            h_obs = _finite(home.get("offense_touchdowns"), "home.offense_touchdowns") + _finite(
                home.get("made_field_goals"), "home.made_field_goals"
            )
            a_obs = _finite(away.get("offense_touchdowns"), "away.offense_touchdowns") + _finite(
                away.get("made_field_goals"), "away.made_field_goals"
            )
            residual_rows.append({
                "game_id": gid,
                "season": validation_season,
                "home_mu": h_mu,
                "away_mu": a_mu,
                "residual_product": (h_obs - h_mu) * (a_obs - a_mu),
            })
        fold_meta.append({
            "validation_season": validation_season,
            "training_seasons": train_seasons,
            "n_team_rows": len(valid),
            "n_games": len(pairs),
            "td_alpha": td_alpha,
            "fg_alpha": fg_alpha,
            "fg_feature_names": list(fg_feature_names),
            "td_alpha_cv": {str(k): td_cv[k] for k in sorted(td_cv)},
            "fg_alpha_cv": {str(k): fg_cv[k] for k in sorted(fg_cv)},
        })
    if not residual_rows:
        raise ScoreCountArtifactError("SIGMA_OOF_ROWS_EMPTY")

    mse: dict[float, float] = {}
    for sigma in SIGMA_GRID:
        errors = []
        for row in residual_rows:
            implied = float(row["home_mu"]) * float(row["away_mu"]) * (exp(float(sigma) ** 2) - 1.0)
            errors.append((float(row["residual_product"]) - implied) ** 2)
        mse[float(sigma)] = float(np.mean(np.asarray(errors, dtype=float)))
    best = min(mse, key=lambda s: (mse[s], s))
    return float(best), {
        "metric": "MSE_RESIDUAL_PRODUCT_VS_LOGNORMAL_IMPLIED_COVARIANCE",
        "sigma_grid": list(SIGMA_GRID),
        "mse_by_sigma": {str(k): mse[k] for k in sorted(mse)},
        "selected_sigma": float(best),
        "oof_game_count": len(residual_rows),
        "folds": fold_meta,
    }


def _league_priors(rows: Sequence[Mapping[str, Any]]) -> tuple[float, float, tuple[float, float, float]]:
    n = len(rows)
    if n <= 0:
        raise ScoreCountArtifactError("TRAINING_ROWS_REQUIRED")
    dst = sum(_finite(row.get("def_st_touchdowns"), "def_st_touchdowns") for row in rows) / n
    safety = sum(_finite(row.get("safeties"), "safeties") for row in rows) / n
    pat = sum(_finite(row.get("pat_made"), "pat_made") for row in rows)
    two = sum(_finite(row.get("two_point_made"), "two_point_made") for row in rows)
    no = sum(_finite(row.get("no_conversion"), "no_conversion") for row in rows)
    total = pat + two + no
    if total <= 0:
        raise ScoreCountArtifactError("CONVERSION_TD_EXPOSURE_REQUIRED")
    probs = (pat / total, two / total, no / total)
    return float(dst), float(safety), tuple(float(v) for v in probs)


def build_attempt_fit_artifact(
    rows: Sequence[Mapping[str, Any]],
    *,
    attempt_number: int,
    source_manifest_sha256: str,
    code_identity: str,
    prereg_addendum_sha256: str,
) -> dict[str, Any]:
    if int(attempt_number) not in {1, 2, 3}:
        raise ScoreCountArtifactError("ATTEMPT_NUMBER_OUT_OF_FROZEN_BUDGET")
    source_sha = _sha(source_manifest_sha256, "source_manifest_sha256")
    prereg_sha = _sha(prereg_addendum_sha256, "prereg_addendum_sha256")
    code = str(code_identity or "").strip()
    if not code:
        raise ScoreCountArtifactError("CODE_IDENTITY_REQUIRED")
    materialized = [dict(row) for row in rows]
    if sorted({int(row["season"]) for row in materialized}) != list(DEVELOPMENT_SEASONS):
        raise ScoreCountArtifactError("DEVELOPMENT_SEASONS_EXACT_REQUIRED")
    development_gate = _development_count_gate(
        materialized, attempt_number=int(attempt_number)
    )
    sigma, sigma_diag = _select_shared_sigma(
        materialized, attempt_number=int(attempt_number)
    )
    dst, safety, conversions = _league_priors(materialized)
    td_alpha, td_cv = choose_alpha(
        materialized, target="offense_touchdowns", alphas=ALPHA_GRID
    )
    fg_feature_names, fg_alpha_grid = _attempt_fg_spec(int(attempt_number))
    fg_alpha, fg_cv = choose_alpha(
        materialized,
        target="made_field_goals",
        alphas=fg_alpha_grid,
        feature_names=fg_feature_names,
    )
    fit = fit_core(
        materialized,
        shared_sigma=sigma,
        def_st_td_rate=dst,
        safety_rate=safety,
        conversion_probabilities=conversions,
        source_manifest_sha256=source_sha,
        code_identity=code,
        fg_feature_names=fg_feature_names,
        fg_alphas=fg_alpha_grid,
    )
    if fit.td_model.alpha != td_alpha or fit.fg_model.alpha != fg_alpha:
        raise ScoreCountArtifactError("FIT_ALPHA_REPLAY_MISMATCH")
    game_count = len(_game_pairs(materialized))
    payload: dict[str, Any] = {
        "schema": FIT_SCHEMA,
        "status": "DEVELOPMENT_ATTEMPT_PASS" if development_gate["pass"] else "DEVELOPMENT_ATTEMPT_FAIL",
        "candidate_family": "NFL_SCORE_COUNTS_G1",
        "attempt_number": int(attempt_number),
        "development_seasons": list(DEVELOPMENT_SEASONS),
        "team_row_count": len(materialized),
        "game_count": game_count,
        "source_manifest_sha256": source_sha,
        "prereg_addendum_sha256": prereg_sha,
        "code_identity": code,
        "rng": {
            "algorithm": "NUMPY_PCG64_SEEDSEQUENCE",
            "root_seed_literal": ROOT_SEED_LITERAL,
            "root_seed_uint64": str(ROOT_SEED_UINT64),
            "scored_paths_per_game": 50000,
        },
        "development_gate": development_gate,
        "selection": {
            "alpha_grid": list(ALPHA_GRID),
            "td_alpha": td_alpha,
            "fg_alpha": fg_alpha,
            "fg_feature_names": list(fg_feature_names),
            "fg_alpha_grid": list(fg_alpha_grid),
            "td_alpha_cv": {str(k): td_cv[k] for k in sorted(td_cv)},
            "fg_alpha_cv": {str(k): fg_cv[k] for k in sorted(fg_cv)},
            "shared_sigma": sigma_diag,
        },
        "fit": {
            "td_model": _poisson_dict(fit.td_model),
            "fg_model": _poisson_dict(fit.fg_model),
            "shared_sigma": fit.shared_sigma,
            "def_st_td_rate": fit.def_st_td_rate,
            "safety_rate": fit.safety_rate,
            "conversion_probabilities": list(fit.conversion_probabilities),
            "source_manifest_sha256": fit.source_manifest_sha256,
            "code_identity": fit.code_identity,
        },
        "authority": {
            "research_only": True,
            "creates_model_p": False,
            "pricing": False,
            "truth_gate": False,
            "promotion": False,
            "staking": False,
            "official": False,
            "backfill": False,
        },
    }
    payload["artifact_sha256"] = _digest(payload)
    return payload


def _assert_forward_row(row: Mapping[str, Any], prediction_at: datetime) -> None:
    bad = [key for key in row if str(key).lower() in FORBIDDEN_FORWARD_FIELDS]
    if bad:
        raise ScoreCountArtifactError("FORWARD_ROW_FORBIDDEN_FIELD:" + ",".join(sorted(bad)))
    if int(row.get("season", -1)) != FORWARD_SEASON:
        raise ScoreCountArtifactError("FORWARD_SEASON_REQUIRED")
    if int(row.get("week", -1)) < FORWARD_FIRST_WEEK:
        raise ScoreCountArtifactError("FORWARD_WEEK_BEFORE_FROZEN_BOUNDARY")
    kickoff = _utc(row.get("game_start_ts"), "game_start_ts")
    if kickoff < _utc(FORWARD_FIRST_KICKOFF, "first_eligible_kickoff"):
        raise ScoreCountArtifactError("FORWARD_KICKOFF_BEFORE_FROZEN_BOUNDARY")
    if not prediction_at < kickoff:
        raise ScoreCountArtifactError("PREDICTION_MUST_PRECEDE_KICKOFF")


def build_forward_prediction(
    fit_artifact: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    prediction_at: Any,
    source_manifest_sha256: str,
    code_identity: str,
    paths: int = 50000,
) -> dict[str, Any]:
    if int(paths) != 50000:
        raise ScoreCountArtifactError("FORWARD_PATH_COUNT_MUST_EQUAL_50000")
    stamp = _utc(prediction_at, "prediction_at")
    fit = fit_from_artifact(fit_artifact)
    source_sha = _sha(source_manifest_sha256, "source_manifest_sha256")
    if source_sha != fit.source_manifest_sha256:
        raise ScoreCountArtifactError("FORWARD_SOURCE_MANIFEST_MISMATCH")
    code = str(code_identity or "").strip()
    if not code or code != fit.code_identity:
        raise ScoreCountArtifactError("FORWARD_CODE_IDENTITY_MISMATCH")

    materialized = [dict(row) for row in rows]
    for row in materialized:
        _assert_forward_row(row, stamp)
    games = _game_pairs(materialized)
    out_games = []
    for gid, (home, away) in sorted(games.items()):
        simulation = simulate_game(
            fit,
            game_id=gid,
            home_row=home,
            away_row=away,
            paths=50000,
            seed=None,
        )
        home_scores = np.asarray(simulation["home_score"], dtype=int)
        away_scores = np.asarray(simulation["away_score"], dtype=int)
        home_tds = np.asarray(simulation["home_team_tds"], dtype=int)
        away_tds = np.asarray(simulation["away_team_tds"], dtype=int)

        pairs = np.column_stack([home_scores, away_scores])
        unique, counts = np.unique(pairs, axis=0, return_counts=True)
        distribution = [
            [int(score[0]), int(score[1]), int(count)]
            for score, count in zip(unique, counts)
        ]
        dist_sha = _digest(distribution)

        component_pairs = np.column_stack(
            [home_scores, away_scores, home_tds, away_tds]
        )
        component_unique, component_counts = np.unique(
            component_pairs, axis=0, return_counts=True
        )
        td_distribution = [
            [
                int(state[0]),
                int(state[1]),
                int(state[2]),
                int(state[3]),
                int(count),
            ]
            for state, count in zip(component_unique, component_counts)
        ]
        td_dist_sha = _digest(td_distribution)
        feature_digest = {
            "home": str(home.get("feature_digest") or ""),
            "away": str(away.get("feature_digest") or ""),
        }
        if any(len(v) != 64 for v in feature_digest.values()):
            raise ScoreCountArtifactError(f"FEATURE_DIGEST_REQUIRED:{gid}")
        out_games.append({
            "game_id": gid,
            "season": int(home["season"]),
            "week": int(home["week"]),
            "kickoff_at": _utc(home["game_start_ts"], "game_start_ts").isoformat(),
            "home_team": str(home.get("team") or ""),
            "away_team": str(away.get("team") or ""),
            "prediction_at": stamp.isoformat(),
            "feature_digest": feature_digest,
            "seed": int(simulation["seed"]),
            "paths": 50000,
            "joint_score_distribution": distribution,
            "joint_score_distribution_sha256": dist_sha,
            "joint_score_td_distribution": td_distribution,
            "joint_score_td_distribution_sha256": td_dist_sha,
            "means": dict(simulation["means"]),
            "model": dict(simulation["model"]),
        })

    payload: dict[str, Any] = {
        "schema": PREDICTION_SCHEMA,
        "status": "FROZEN_PREGAME_RESEARCH_PREDICTION",
        "candidate_family": "NFL_SCORE_COUNTS_G1",
        "fit_artifact_sha256": str(fit_artifact["artifact_sha256"]),
        "source_manifest_sha256": source_sha,
        "code_identity": code,
        "prediction_at": stamp.isoformat(),
        "games": out_games,
        "market_data_present": False,
        "outcome_data_present": False,
        "authority": {
            "research_only": True,
            "creates_model_p": False,
            "pricing": False,
            "truth_gate": False,
            "promotion": False,
            "staking": False,
            "official": False,
            "backfill": False,
        },
    }
    payload["prediction_sha256"] = _digest(payload)
    return payload


__all__ = [
    "DEVELOPMENT_SEASONS",
    "FIT_SCHEMA",
    "FORWARD_FIRST_KICKOFF",
    "FORWARD_FIRST_WEEK",
    "FORWARD_SEASON",
    "PREDICTION_SCHEMA",
    "ScoreCountArtifactError",
    "build_attempt_fit_artifact",
    "build_forward_prediction",
    "fit_from_artifact",
]
