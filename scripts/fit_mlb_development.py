#!/usr/bin/env python3
"""Develop MLB score features without touching the sacred 2025 holdout.

This runner is intentionally capped at 2024.  It uses free MLB StatsAPI final
scores only, builds point-in-time features from strictly prior dates, selects
ridge alpha on pre-2024 training rows with date-blocked forward chaining, and
uses 2024 only as DEVELOPMENT validation.  It is research-only and cannot
produce Model_P, Truth Gate evidence, eligibility, or OFFICIAL plays.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from itertools import groupby
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.fit_mlb_baseline import (  # noqa: E402
    ALPHAS,
    MIN_PRIOR,
    _canonical_sha256,
    _normalize_schedule_duplicates,
    fetch_season,
    ridge_fit,
    standardize,
)

MAX_DEVELOPMENT_SEASON = 2024
DEFAULT_SEASONS = (2021, 2022, 2023, 2024)
DEFAULT_VALIDATION_SEASON = 2024


class MLBDevelopmentError(ValueError):
    pass


def validate_development_window(seasons: list[int], validation_season: int) -> None:
    if not seasons or len(set(seasons)) < 3:
        raise MLBDevelopmentError("MLB_DEV_SEASONS_INSUFFICIENT")
    if any(year > MAX_DEVELOPMENT_SEASON for year in seasons):
        raise MLBDevelopmentError("MLB_DEV_POST_2024_FORBIDDEN")
    if validation_season > MAX_DEVELOPMENT_SEASON:
        raise MLBDevelopmentError("MLB_DEV_POST_2024_FORBIDDEN")
    if validation_season not in seasons:
        raise MLBDevelopmentError("MLB_DEV_VALIDATION_SEASON_MISSING")
    if validation_season != max(seasons):
        raise MLBDevelopmentError("MLB_DEV_VALIDATION_MUST_BE_LATEST_SEASON")
    if len([year for year in seasons if year < validation_season]) < 2:
        raise MLBDevelopmentError("MLB_DEV_TRAIN_SEASONS_INSUFFICIENT")


def _mean_tail(values: list[float], n: int) -> float:
    tail = values[-n:]
    return float(np.mean(tail)) if tail else 0.0


def _mean(values: list[float]) -> float:
    return float(np.mean(values)) if values else 0.0


def _day_gap(last_played: dict[int, str], team: int, date: str) -> float:
    import datetime as dt

    previous = last_played.get(team)
    if not previous:
        return 1.0
    a = dt.date.fromisoformat(previous)
    b = dt.date.fromisoformat(date)
    return float(min(max((b - a).days, 0), 7))


def build_feature_sets(games: list[dict[str, Any]]) -> tuple[dict[str, tuple[np.ndarray, list[str]]], np.ndarray, np.ndarray, list[str], list[int]]:
    """Build baseline and candidate matrices from a shared prior-date snapshot."""
    games = sorted(games, key=lambda row: (str(row["date"]), int(row["game_pk"])))
    scored: dict[int, list[float]] = defaultdict(list)
    allowed: dict[int, list[float]] = defaultdict(list)
    home_scored: dict[int, list[float]] = defaultdict(list)
    home_allowed: dict[int, list[float]] = defaultdict(list)
    away_scored: dict[int, list[float]] = defaultdict(list)
    away_allowed: dict[int, list[float]] = defaultdict(list)
    season_scored: dict[tuple[int, int], list[float]] = defaultdict(list)
    season_allowed: dict[tuple[int, int], list[float]] = defaultdict(list)
    last_played: dict[int, str] = {}

    baseline_names = [
        "home_rs_roll30", "home_ra_roll30", "away_rs_roll30", "away_ra_roll30",
        "home_net_roll30", "away_net_roll30", "home_rs_home_split30",
        "away_rs_away_split30", "home_rest_days_cap7", "away_rest_days_cap7",
    ]
    candidate_names = [
        "home_rs_roll10", "home_ra_roll10", "away_rs_roll10", "away_ra_roll10",
        "home_rs_roll30", "home_ra_roll30", "away_rs_roll30", "away_ra_roll30",
        "home_season_rs", "home_season_ra", "away_season_rs", "away_season_ra",
        "home_rs_home_split30", "home_ra_home_split30",
        "away_rs_away_split30", "away_ra_away_split30",
        "home_rest_days_cap7", "away_rest_days_cap7",
        "home_back_to_back", "away_back_to_back",
        "home_long_rest_gt2", "away_long_rest_gt2",
    ]
    baseline_rows: list[list[float]] = []
    candidate_rows: list[list[float]] = []
    margins: list[float] = []
    totals: list[float] = []
    dates: list[str] = []
    game_pks: list[int] = []

    for date_value, grouped in groupby(games, key=lambda row: str(row["date"])):
        date_games = list(grouped)
        season = int(date_value[:4])
        for game in date_games:
            home = int(game["home_id"]); away = int(game["away_id"])
            if len(scored[home]) < MIN_PRIOR or len(scored[away]) < MIN_PRIOR:
                continue

            h_rs30 = _mean_tail(scored[home], 30); h_ra30 = _mean_tail(allowed[home], 30)
            a_rs30 = _mean_tail(scored[away], 30); a_ra30 = _mean_tail(allowed[away], 30)
            h_rest = _day_gap(last_played, home, date_value)
            a_rest = _day_gap(last_played, away, date_value)
            baseline_rows.append([
                h_rs30, h_ra30, a_rs30, a_ra30,
                h_rs30 - h_ra30, a_rs30 - a_ra30,
                _mean_tail(home_scored[home], 30), _mean_tail(away_scored[away], 30),
                h_rest, a_rest,
            ])
            candidate_rows.append([
                _mean_tail(scored[home], 10), _mean_tail(allowed[home], 10),
                _mean_tail(scored[away], 10), _mean_tail(allowed[away], 10),
                h_rs30, h_ra30, a_rs30, a_ra30,
                _mean(season_scored[(season, home)]), _mean(season_allowed[(season, home)]),
                _mean(season_scored[(season, away)]), _mean(season_allowed[(season, away)]),
                _mean_tail(home_scored[home], 30), _mean_tail(home_allowed[home], 30),
                _mean_tail(away_scored[away], 30), _mean_tail(away_allowed[away], 30),
                h_rest, a_rest,
                1.0 if h_rest <= 1.0 else 0.0, 1.0 if a_rest <= 1.0 else 0.0,
                1.0 if h_rest > 2.0 else 0.0, 1.0 if a_rest > 2.0 else 0.0,
            ])
            margins.append(float(game["home_score"] - game["away_score"]))
            totals.append(float(game["home_score"] + game["away_score"]))
            dates.append(date_value)
            game_pks.append(int(game["game_pk"]))

        # Update only after every game on this date has been emitted.
        for game in date_games:
            home = int(game["home_id"]); away = int(game["away_id"])
            hs = float(game["home_score"]); aws = float(game["away_score"])
            scored[home].append(hs); allowed[home].append(aws)
            scored[away].append(aws); allowed[away].append(hs)
            home_scored[home].append(hs); home_allowed[home].append(aws)
            away_scored[away].append(aws); away_allowed[away].append(hs)
            season_scored[(season, home)].append(hs); season_allowed[(season, home)].append(aws)
            season_scored[(season, away)].append(aws); season_allowed[(season, away)].append(hs)
            last_played[home] = last_played[away] = date_value

    feature_sets = {
        "baseline_v1": (np.asarray(baseline_rows, dtype=float), baseline_names),
        "pit_multiwindow_v1": (np.asarray(candidate_rows, dtype=float), candidate_names),
    }
    return feature_sets, np.asarray(margins, dtype=float), np.asarray(totals, dtype=float), dates, game_pks


def date_forward_cv_splits(dates: list[str], folds: int = 4) -> list[tuple[np.ndarray, np.ndarray]]:
    """Expanding CV split on whole dates so same-date outcomes never cross a fold."""
    unique_dates = sorted(set(dates))
    if len(unique_dates) < folds + 2:
        raise MLBDevelopmentError("MLB_DEV_CV_DATES_INSUFFICIENT")
    splits: list[tuple[np.ndarray, np.ndarray]] = []
    date_array = np.asarray(dates)
    for k in range(1, folds + 1):
        cut_pos = int(len(unique_dates) * k / (folds + 1))
        end_pos = int(len(unique_dates) * (k + 1) / (folds + 1))
        if end_pos <= cut_pos:
            raise MLBDevelopmentError("MLB_DEV_CV_DATE_SPLIT_INVALID")
        train_dates = set(unique_dates[:cut_pos])
        valid_dates = set(unique_dates[cut_pos:end_pos])
        train_idx = np.where(np.isin(date_array, list(train_dates)))[0]
        valid_idx = np.where(np.isin(date_array, list(valid_dates)))[0]
        if not len(train_idx) or not len(valid_idx):
            raise MLBDevelopmentError("MLB_DEV_CV_ROWS_INSUFFICIENT")
        if set(date_array[train_idx]) & set(date_array[valid_idx]):
            raise MLBDevelopmentError("MLB_DEV_CV_SAME_DATE_LEAKAGE")
        if max(date_array[train_idx]) >= min(date_array[valid_idx]):
            raise MLBDevelopmentError("MLB_DEV_CV_TEMPORAL_ORDER_INVALID")
        splits.append((train_idx, valid_idx))
    return splits


def select_alpha(X: np.ndarray, y: np.ndarray, dates: list[str]) -> tuple[float, dict[str, Any]]:
    splits = date_forward_cv_splits(dates)
    scores: dict[float, list[float]] = {alpha: [] for alpha in ALPHAS}
    fold_meta: list[dict[str, Any]] = []
    for train_idx, valid_idx in splits:
        Xtr, Xva = standardize(X[train_idx], X[valid_idx])
        ytr, yva = y[train_idx], y[valid_idx]
        for alpha in ALPHAS:
            beta, intercept = ridge_fit(Xtr, ytr, alpha)
            pred = Xva @ beta + intercept
            scores[alpha].append(float(np.mean((pred - yva) ** 2)))
        fold_meta.append({
            "train_end_date": dates[int(train_idx[-1])],
            "validation_start_date": dates[int(valid_idx[0])],
            "validation_end_date": dates[int(valid_idx[-1])],
            "train_rows": int(len(train_idx)),
            "validation_rows": int(len(valid_idx)),
        })
    mean_mse = {alpha: float(np.mean(values)) for alpha, values in scores.items()}
    selected = min(mean_mse, key=lambda alpha: (mean_mse[alpha], alpha))
    return float(selected), {
        "metric": "MSE",
        "tie_break": "LOWEST_MSE_THEN_LOWEST_ALPHA",
        "date_blocked_forward_chaining": True,
        "folds": fold_meta,
        "grid_mse": {str(alpha): value for alpha, value in mean_mse.items()},
    }


def evaluate(Xtr: np.ndarray, ytr: np.ndarray, Xva: np.ndarray, yva: np.ndarray, alpha: float) -> dict[str, float]:
    Xtr_s, Xva_s = standardize(Xtr, Xva)
    beta, intercept = ridge_fit(Xtr_s, ytr, alpha)
    pred = Xva_s @ beta + intercept
    mse = float(np.mean((pred - yva) ** 2))
    base_mse = float(np.mean((ytr.mean() - yva) ** 2))
    return {
        "rmse": float(np.sqrt(mse)),
        "baseline_rmse": float(np.sqrt(base_mse)),
        "r2_vs_mean": float(1.0 - mse / base_mse) if base_mse else 0.0,
        "mae": float(np.mean(np.abs(pred - yva))),
    }


def coefficient_diagnostics(X: np.ndarray, y: np.ndarray, dates: list[str], names: list[str], alpha: float) -> dict[str, Any]:
    Xs, _ = standardize(X, X)
    beta, intercept = ridge_fit(Xs, y, alpha)
    fold_betas: list[np.ndarray] = []
    for train_idx, _ in date_forward_cv_splits(dates):
        fold_X, _ = standardize(X[train_idx], X[train_idx])
        fold_beta, _ = ridge_fit(fold_X, y[train_idx], alpha)
        fold_betas.append(fold_beta)
    matrix = np.asarray(fold_betas)
    features: dict[str, Any] = {}
    for index, name in enumerate(names):
        values = matrix[:, index]
        stability = max(float(np.mean(values > 1e-12)), float(np.mean(values < -1e-12)), float(np.mean(np.abs(values) <= 1e-12)))
        features[name] = {
            "beta": float(beta[index]),
            "fold_betas": [float(value) for value in values],
            "sign_stability": stability,
            "fold_std": float(np.std(values)),
        }
    return {
        "intercept": float(intercept),
        "features": features,
        "by_magnitude": [name for name, _ in sorted(zip(names, np.abs(beta)), key=lambda item: -item[1])],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", default=",".join(str(year) for year in DEFAULT_SEASONS))
    parser.add_argument("--validation-season", type=int, default=DEFAULT_VALIDATION_SEASON)
    parser.add_argument("--out", default="artifacts/mlb_development_report.json")
    args = parser.parse_args()

    try:
        seasons = [int(value) for value in args.seasons.split(",") if value.strip()]
        validate_development_window(seasons, args.validation_season)
    except (ValueError, MLBDevelopmentError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    games: list[dict[str, Any]] = []
    per_season: dict[int, int] = {}
    for season in seasons:
        if season > MAX_DEVELOPMENT_SEASON:  # defense in depth before HTTP
            print("MLB_DEV_POST_2024_FORBIDDEN", file=sys.stderr)
            return 2
        rows = fetch_season(season)
        per_season[season] = len(rows)
        games.extend(rows)
        print(f"{season}: {len(rows)} final rows", flush=True)

    raw_games = sorted(games, key=lambda row: (str(row["date"]), int(row["game_pk"])))
    try:
        canonical_games, duplicate_normalization = _normalize_schedule_duplicates(raw_games)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    feature_sets, y_margin, y_total, dates, game_pks = build_feature_sets(canonical_games)
    valid_mask = np.asarray([date.startswith(str(args.validation_season)) for date in dates])
    train_mask = ~valid_mask
    if int(valid_mask.sum()) < 200 or int(train_mask.sum()) < 500:
        print("MLB_DEV_SPLIT_INSUFFICIENT", file=sys.stderr)
        return 2
    train_dates = [date for date, flag in zip(dates, train_mask) if bool(flag)]

    row_identity = [{"date": date, "game_pk": int(game_pk)} for date, game_pk in zip(dates, game_pks)]
    report: dict[str, Any] = {
        "schema": "MLB_DEVELOPMENT_REPORT_V1",
        "status": "RESEARCH_ONLY_NOT_MODEL_P",
        "promotion_changed": False,
        "truth_gate_evidence": False,
        "official_evidence": False,
        "holdout_class": "DEVELOPMENT_VALIDATION_NOT_FINAL",
        "sacred_2025_accessed": False,
        "max_allowed_season": MAX_DEVELOPMENT_SEASON,
        "seasons": per_season,
        "validation_season": args.validation_season,
        "source": "MLB StatsAPI free schedule/final-score endpoint; no odds provider",
        "input_provenance": {
            "raw_rows": len(raw_games),
            "raw_rows_sha256": _canonical_sha256(raw_games),
            "normalized_rows": len(canonical_games),
            "normalized_rows_sha256": _canonical_sha256(canonical_games),
            "duplicate_normalization": duplicate_normalization,
            "usable_rows": len(dates),
            "row_identity_sha256": _canonical_sha256(row_identity),
            "train_row_identity_sha256": _canonical_sha256([row for row, flag in zip(row_identity, train_mask) if bool(flag)]),
            "validation_row_identity_sha256": _canonical_sha256([row for row, flag in zip(row_identity, valid_mask) if bool(flag)]),
        },
        "targets": {},
    }

    rng = np.random.default_rng(0)
    for target_name, target in (("margin", y_margin), ("total", y_total)):
        target_report: dict[str, Any] = {"feature_sets": {}}
        for feature_set_name, (X, names) in feature_sets.items():
            Xtr, Xva = X[train_mask], X[valid_mask]
            ytr, yva = target[train_mask], target[valid_mask]
            alpha, cv = select_alpha(Xtr, ytr, train_dates)
            shuffled = ytr.copy(); rng.shuffle(shuffled)
            placebo = evaluate(Xtr, shuffled, Xva, yva, alpha)
            development = evaluate(Xtr, ytr, Xva, yva, alpha)
            diagnostics = coefficient_diagnostics(Xtr, ytr, train_dates, names, alpha)
            target_report["feature_sets"][feature_set_name] = {
                "feature_names": names,
                "selected_alpha": alpha,
                "alpha_selection": cv,
                "coefficients": diagnostics,
                "placebo_2024": placebo,
                "development_2024": development,
            }
        base = target_report["feature_sets"]["baseline_v1"]["development_2024"]
        candidate = target_report["feature_sets"]["pit_multiwindow_v1"]["development_2024"]
        target_report["candidate_vs_baseline"] = {
            "rmse_delta_candidate_minus_baseline": float(candidate["rmse"] - base["rmse"]),
            "r2_delta_candidate_minus_baseline": float(candidate["r2_vs_mean"] - base["r2_vs_mean"]),
            "development_preference": "pit_multiwindow_v1" if candidate["rmse"] < base["rmse"] else "baseline_v1",
            "promotion_implication": "NONE_DEVELOPMENT_ONLY",
        }
        report["targets"][target_name] = target_report

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for target, result in report["targets"].items():
        comparison = result["candidate_vs_baseline"]
        print(f"{target}: preference={comparison['development_preference']} rmse_delta={comparison['rmse_delta_candidate_minus_baseline']:+.4f}")
    print("RESEARCH ONLY / 2021-2024 DEVELOPMENT / 2025 NOT ACCESSED / NOT Model_P / NOT OFFICIAL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
