#!/usr/bin/env python3
"""MLB starter-context development experiment, hard-capped at 2024.

V1 showed a broad multi-window expansion was essentially flat. V2 showed that
park/run-environment context did not improve 2024 development RMSE. This third,
predeclared experiment tests one stronger baseball hypothesis: whether the
listed starting pitcher's prior-start run-prevention history adds signal beyond
baseline team scoring/allowance form.

The source is the free MLB StatsAPI schedule endpoint hydrated with
``probablePitcher``. Historical pitcher identity returned today is NOT an
archived pregame snapshot, so this lane is research only. Every numeric pitcher
feature uses only games on dates strictly before the target game. 2025 is
rejected before HTTP and is never evaluated here.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date as Date
from hashlib import sha256
from itertools import groupby
import json
from pathlib import Path
import sys
import time
from typing import Any
import urllib.request

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.fit_mlb_baseline import (  # noqa: E402
    MIN_PRIOR,
    STATSAPI,
    _canonical_sha256,
    _normalize_schedule_duplicates,
)
from scripts.fit_mlb_development import (  # noqa: E402
    MAX_DEVELOPMENT_SEASON,
    build_feature_sets,
    coefficient_diagnostics,
    evaluate,
    select_alpha,
    validate_development_window,
)

RESEARCH_VERSION = "MLB_DEVELOPMENT_STARTER_CONTEXT_V3"
DEFAULT_SEASONS = (2021, 2022, 2023, 2024)
DEFAULT_VALIDATION_SEASON = 2024
STARTER_SHRINK_STARTS = 4.0
STARTER_FEATURE_NAMES = [
    "home_sp_ra5_delta_team_ra30_shrunk",
    "away_sp_ra5_delta_team_ra30_shrunk",
    "home_sp_ra10_delta_team_ra30_shrunk",
    "away_sp_ra10_delta_team_ra30_shrunk",
    "home_sp_days_since_prior_start_cap14",
    "away_sp_days_since_prior_start_cap14",
    "home_sp_prior_starts_cap10",
    "away_sp_prior_starts_cap10",
    "home_sp_identity_available",
    "away_sp_identity_available",
]
DERIVATION_SURFACE = (
    "scripts/fit_mlb_baseline.py",
    "scripts/fit_mlb_development.py",
    "scripts/fit_mlb_development_v3.py",
)


class MLBDevelopmentV3Error(ValueError):
    pass


def _derivation_sha256() -> str:
    digest = sha256()
    for relative in DERIVATION_SURFACE:
        raw = (ROOT / relative).read_bytes()
        digest.update(relative.encode("utf-8")); digest.update(b"\0")
        digest.update(raw); digest.update(b"\0")
    return digest.hexdigest()


def fetch_season_with_starters(year: int, *, retries: int = 3) -> list[dict[str, Any]]:
    """Fetch final regular-season games plus current historical probablePitcher metadata."""
    if int(year) > MAX_DEVELOPMENT_SEASON:
        raise MLBDevelopmentV3Error("MLB_DEV_V3_POST_2024_HTTP_FORBIDDEN")
    url = (
        f"{STATSAPI}?sportId=1&season={year}"
        f"&startDate={year}-03-01&endDate={year}-11-15"
        "&gameType=R&hydrate=probablePitcher"
        "&fields=dates,date,games,gamePk,status,codedGameState,teams,home,away,"
        "team,id,name,score,probablePitcher,fullName"
    )
    last: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=90) as response:
                payload = json.load(response)
            break
        except Exception as exc:
            last = exc
            time.sleep(2 * (attempt + 1))
    else:
        raise RuntimeError(f"MLB StatsAPI failed for {year}: {last}")

    rows: list[dict[str, Any]] = []
    for day in payload.get("dates", []):
        for game in day.get("games", []):
            if game.get("status", {}).get("codedGameState") != "F":
                continue
            home = game.get("teams", {}).get("home", {})
            away = game.get("teams", {}).get("away", {})
            if "score" not in home or "score" not in away:
                continue
            home_team = home.get("team") or {}
            away_team = away.get("team") or {}
            home_sp = home.get("probablePitcher") or {}
            away_sp = away.get("probablePitcher") or {}
            rows.append({
                "game_pk": int(game["gamePk"]),
                "date": str(day["date"]),
                "home_id": int(home_team["id"]),
                "away_id": int(away_team["id"]),
                "home_score": int(home["score"]),
                "away_score": int(away["score"]),
                "home_starter_id": int(home_sp.get("id") or 0),
                "away_starter_id": int(away_sp.get("id") or 0),
            })
    return rows


def _mean_tail(values: list[float], size: int) -> float:
    tail = values[-size:]
    return float(np.mean(np.asarray(tail, dtype=float))) if tail else 0.0


def _days_since(last_dates: dict[int, str], pitcher_id: int, current_date: str) -> float:
    if not pitcher_id or pitcher_id not in last_dates:
        return 5.0
    gap = (Date.fromisoformat(current_date) - Date.fromisoformat(last_dates[pitcher_id])).days
    return float(min(max(gap, 0), 14))


def _shrunk_delta(prior_allowed: list[float], team_ra30: float, window: int) -> float:
    values = prior_allowed[-window:]
    if not values:
        return 0.0
    pitcher_ra = float(np.mean(np.asarray(values, dtype=float)))
    weight = len(values) / (len(values) + STARTER_SHRINK_STARTS)
    return float((pitcher_ra - team_ra30) * weight)


def build_starter_extras(
    games: list[dict[str, Any]],
) -> tuple[np.ndarray, list[str], list[str], list[int], dict[str, int]]:
    """Build pitcher context from the same prior-date boundary as V1."""
    games = sorted(games, key=lambda row: (str(row["date"]), int(row["game_pk"])))
    scored: dict[int, list[float]] = defaultdict(list)
    allowed: dict[int, list[float]] = defaultdict(list)
    pitcher_team_allowed: dict[int, list[float]] = defaultdict(list)
    pitcher_last_start: dict[int, str] = {}
    pitcher_start_count: dict[int, int] = defaultdict(int)
    rows: list[list[float]] = []
    dates: list[str] = []
    game_pks: list[int] = []
    coverage = {
        "usable_rows": 0,
        "home_identity_available": 0,
        "away_identity_available": 0,
        "both_identities_available": 0,
        "home_prior_start_available": 0,
        "away_prior_start_available": 0,
        "both_prior_starts_available": 0,
    }

    for current_date, grouped in groupby(games, key=lambda row: str(row["date"])):
        day_games = list(grouped)
        for game in day_games:
            home = int(game["home_id"]); away = int(game["away_id"])
            if len(scored[home]) < MIN_PRIOR or len(scored[away]) < MIN_PRIOR:
                continue
            home_sp = int(game.get("home_starter_id") or 0)
            away_sp = int(game.get("away_starter_id") or 0)
            home_team_ra30 = _mean_tail(allowed[home], 30)
            away_team_ra30 = _mean_tail(allowed[away], 30)
            home_prior = pitcher_team_allowed[home_sp] if home_sp else []
            away_prior = pitcher_team_allowed[away_sp] if away_sp else []
            rows.append([
                _shrunk_delta(home_prior, home_team_ra30, 5),
                _shrunk_delta(away_prior, away_team_ra30, 5),
                _shrunk_delta(home_prior, home_team_ra30, 10),
                _shrunk_delta(away_prior, away_team_ra30, 10),
                _days_since(pitcher_last_start, home_sp, current_date),
                _days_since(pitcher_last_start, away_sp, current_date),
                float(min(pitcher_start_count[home_sp], 10)) if home_sp else 0.0,
                float(min(pitcher_start_count[away_sp], 10)) if away_sp else 0.0,
                1.0 if home_sp else 0.0,
                1.0 if away_sp else 0.0,
            ])
            dates.append(current_date)
            game_pks.append(int(game["game_pk"]))
            coverage["usable_rows"] += 1
            coverage["home_identity_available"] += int(bool(home_sp))
            coverage["away_identity_available"] += int(bool(away_sp))
            coverage["both_identities_available"] += int(bool(home_sp and away_sp))
            coverage["home_prior_start_available"] += int(bool(home_prior))
            coverage["away_prior_start_available"] += int(bool(away_prior))
            coverage["both_prior_starts_available"] += int(bool(home_prior and away_prior))

        # Update starter histories only after every game on the date is emitted.
        # The response's current-game final score therefore cannot enter a
        # same-date game's pitcher feature vector.
        for game in day_games:
            home = int(game["home_id"]); away = int(game["away_id"])
            home_score = float(game["home_score"]); away_score = float(game["away_score"])
            scored[home].append(home_score); allowed[home].append(away_score)
            scored[away].append(away_score); allowed[away].append(home_score)
            home_sp = int(game.get("home_starter_id") or 0)
            away_sp = int(game.get("away_starter_id") or 0)
            if home_sp:
                pitcher_team_allowed[home_sp].append(away_score)
                pitcher_start_count[home_sp] += 1
                pitcher_last_start[home_sp] = current_date
            if away_sp:
                pitcher_team_allowed[away_sp].append(home_score)
                pitcher_start_count[away_sp] += 1
                pitcher_last_start[away_sp] = current_date

    return np.asarray(rows, dtype=float), list(STARTER_FEATURE_NAMES), dates, game_pks, coverage


def build_v3_feature_sets(
    games: list[dict[str, Any]],
) -> tuple[dict[str, tuple[np.ndarray, list[str]]], np.ndarray, np.ndarray, list[str], list[int], dict[str, int]]:
    base_sets, margin, total, dates, game_pks = build_feature_sets(games)
    extras, extra_names, extra_dates, extra_game_pks, coverage = build_starter_extras(games)
    if dates != extra_dates or game_pks != extra_game_pks:
        raise MLBDevelopmentV3Error("MLB_DEV_V3_ROW_IDENTITY_MISMATCH")
    if not np.isfinite(extras).all():
        raise MLBDevelopmentV3Error("MLB_DEV_V3_STARTER_FEATURE_NONFINITE")
    baseline, baseline_names = base_sets["baseline_v1"]
    return {
        "baseline_v1": (baseline, list(baseline_names)),
        "pit_starter_v3": (np.column_stack([baseline, extras]), list(baseline_names) + extra_names),
    }, margin, total, dates, game_pks, coverage


def _matrix_sha256(matrix: np.ndarray) -> str:
    return _canonical_sha256([[float(value) for value in row] for row in matrix])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", default=",".join(str(year) for year in DEFAULT_SEASONS))
    parser.add_argument("--validation-season", type=int, default=DEFAULT_VALIDATION_SEASON)
    parser.add_argument("--out", default="artifacts/mlb_development_v3_report.json")
    args = parser.parse_args()

    try:
        seasons = [int(value) for value in args.seasons.split(",") if value.strip()]
        validate_development_window(seasons, args.validation_season)
    except (ValueError, Exception) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if seasons != list(DEFAULT_SEASONS) or args.validation_season != DEFAULT_VALIDATION_SEASON:
        print("MLB_DEV_V3_REQUIRES_EXACT_2021_2024_WINDOW", file=sys.stderr)
        return 2

    games: list[dict[str, Any]] = []
    per_season: dict[int, int] = {}
    for season in seasons:
        if season > MAX_DEVELOPMENT_SEASON:
            print("MLB_DEV_V3_POST_2024_HTTP_FORBIDDEN", file=sys.stderr)
            return 2
        rows = fetch_season_with_starters(season)
        per_season[season] = len(rows)
        games.extend(rows)
        print(f"{season}: {len(rows)} final rows with probablePitcher hydration", flush=True)

    raw_games = sorted(games, key=lambda row: (str(row["date"]), int(row["game_pk"])))
    try:
        canonical_games, duplicate_normalization = _normalize_schedule_duplicates(raw_games)
        feature_sets, y_margin, y_total, dates, game_pks, coverage = build_v3_feature_sets(canonical_games)
    except (ValueError, MLBDevelopmentV3Error) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    valid_mask = np.asarray([date.startswith("2024") for date in dates])
    train_mask = ~valid_mask
    if int(valid_mask.sum()) < 200 or int(train_mask.sum()) < 500:
        print("MLB_DEV_V3_SPLIT_INSUFFICIENT", file=sys.stderr)
        return 2
    train_dates = [date for date, flag in zip(dates, train_mask) if bool(flag)]
    row_identity = [{"date": date, "game_pk": int(pk)} for date, pk in zip(dates, game_pks)]

    coverage_rates = {
        key + "_rate": (float(value) / coverage["usable_rows"] if coverage["usable_rows"] else 0.0)
        for key, value in coverage.items() if key != "usable_rows"
    }
    report: dict[str, Any] = {
        "schema": "MLB_DEVELOPMENT_V3_REPORT_V1",
        "research_version": RESEARCH_VERSION,
        "status": "RESEARCH_ONLY_NOT_MODEL_P",
        "promotion_changed": False,
        "truth_gate_evidence": False,
        "official_evidence": False,
        "sacred_2025_accessed": False,
        "max_allowed_season": MAX_DEVELOPMENT_SEASON,
        "holdout_class": "DEVELOPMENT_VALIDATION_NOT_FINAL",
        "seasons": per_season,
        "validation_season": 2024,
        "source": "MLB StatsAPI free schedule/final-score endpoint hydrated with probablePitcher; no odds provider",
        "starter_metadata_limitation": "Historical probablePitcher identity is current StatsAPI metadata, not an archived pregame snapshot. Numeric features are prior-date-only, but this experiment is not promotion/PIT evidence.",
        "derivation_code_sha256": _derivation_sha256(),
        "derivation_surface": list(DERIVATION_SURFACE),
        "input_provenance": {
            "raw_rows": len(raw_games),
            "raw_rows_sha256": _canonical_sha256(raw_games),
            "normalized_rows": len(canonical_games),
            "normalized_rows_sha256": _canonical_sha256(canonical_games),
            "duplicate_normalization": duplicate_normalization,
            "usable_rows": len(dates),
            "row_identity_sha256": _canonical_sha256(row_identity),
            "feature_matrix_sha256": {name: _matrix_sha256(value[0]) for name, value in feature_sets.items()},
            "starter_coverage_counts": coverage,
            "starter_coverage_rates": coverage_rates,
        },
        "hypothesis": {
            "predeclared_new_family": "pit_starter_v3",
            "new_features": list(STARTER_FEATURE_NAMES),
            "starter_run_prevention_proxy": "TEAM_FINAL_RUNS_ALLOWED_IN_PRIOR_LISTED_STARTS",
            "shrinkage_prior_starts": STARTER_SHRINK_STARTS,
            "combinatorial_feature_search": False,
        },
        "targets": {},
    }

    for target_name, target in (("margin", y_margin), ("total", y_total)):
        target_result: dict[str, Any] = {"feature_sets": {}}
        y_train, y_valid = target[train_mask], target[valid_mask]
        for feature_name, (X, names) in feature_sets.items():
            X_train, X_valid = X[train_mask], X[valid_mask]
            alpha, alpha_policy = select_alpha(X_train, y_train, train_dates)
            metrics = evaluate(X_train, y_train, X_valid, y_valid, alpha)
            diagnostics = coefficient_diagnostics(X_train, y_train, train_dates, names, alpha)
            target_result["feature_sets"][feature_name] = {
                "feature_names": names,
                "selected_alpha": alpha,
                "alpha_selection": alpha_policy,
                "development_2024": metrics,
                "coefficients": diagnostics,
            }
        base_rmse = target_result["feature_sets"]["baseline_v1"]["development_2024"]["rmse"]
        starter_rmse = target_result["feature_sets"]["pit_starter_v3"]["development_2024"]["rmse"]
        target_result["comparison"] = {
            "pit_starter_v3_minus_baseline_rmse": float(starter_rmse - base_rmse),
            "development_preference": "pit_starter_v3" if starter_rmse < base_rmse else "baseline_v1",
            "promotion_implication": "NONE_DEVELOPMENT_ONLY",
        }
        report["targets"][target_name] = target_result

    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "margin": report["targets"]["margin"]["comparison"],
        "total": report["targets"]["total"]["comparison"],
        "starter_coverage_rates": coverage_rates,
        "sacred_2025_accessed": False,
        "promotion_evidence": False,
    }, sort_keys=True))
    print("RESEARCH ONLY / 2021-2024 DEVELOPMENT / 2025 NOT ACCESSED / NOT Model_P / NOT OFFICIAL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
