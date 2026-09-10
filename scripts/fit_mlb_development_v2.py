#!/usr/bin/env python3
"""Second MLB development experiment, hard-capped at 2024.

The first pre-2025 experiment showed essentially no gain from a broad
multi-window feature expansion.  This preregistered follow-up tests one new
hypothesis family: run-environment / park context plus short schedule-load
proxies, all derived from fixture metadata and games strictly before the target
date.  It compares baseline_v1, pit_multiwindow_v1, and pit_context_v2 on the
same 2024 DEVELOPMENT validation rows.

This is not a final holdout.  It cannot access 2025, does not use odds, and does
not produce Model_P, promotion evidence, or OFFICIAL plays.
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

RESEARCH_VERSION = "MLB_DEVELOPMENT_CONTEXT_V2"
DEFAULT_SEASONS = (2021, 2022, 2023, 2024)
DEFAULT_VALIDATION_SEASON = 2024
PARK_SHRINK_GAMES = 50.0
CONTEXT_FEATURE_NAMES = [
    "league_total_roll30",
    "league_total_roll100",
    "league_home_margin_roll100",
    "venue_total_delta_shrunk50",
    "home_games_prior3d",
    "away_games_prior3d",
    "home_ra_roll3",
    "away_ra_roll3",
]
DERIVATION_SURFACE = (
    "scripts/fit_mlb_baseline.py",
    "scripts/fit_mlb_development.py",
    "scripts/fit_mlb_development_v2.py",
)


class MLBDevelopmentV2Error(ValueError):
    pass


def _derivation_sha256() -> str:
    digest = sha256()
    for relative in DERIVATION_SURFACE:
        raw = (ROOT / relative).read_bytes()
        digest.update(relative.encode("utf-8")); digest.update(b"\0")
        digest.update(raw); digest.update(b"\0")
    return digest.hexdigest()


def fetch_season_with_venue(year: int, *, retries: int = 3) -> list[dict[str, Any]]:
    if int(year) > MAX_DEVELOPMENT_SEASON:
        raise MLBDevelopmentV2Error("MLB_DEV_V2_POST_2024_HTTP_FORBIDDEN")
    url = (
        f"{STATSAPI}?sportId=1&season={year}"
        f"&startDate={year}-03-01&endDate={year}-11-15"
        "&gameType=R&fields=dates,date,games,gamePk,status,codedGameState,"
        "teams,home,away,team,id,name,score,venue"
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
            home, away = game["teams"]["home"], game["teams"]["away"]
            if "score" not in home or "score" not in away:
                continue
            venue = game.get("venue") or {}
            rows.append({
                "game_pk": int(game["gamePk"]),
                "date": str(day["date"]),
                "home_id": int(home["team"]["id"]),
                "away_id": int(away["team"]["id"]),
                "home_score": int(home["score"]),
                "away_score": int(away["score"]),
                "venue_id": int(venue.get("id") or 0),
            })
    return rows


def _mean_tail(values: list[float], size: int) -> float:
    tail = values[-size:]
    return float(np.mean(np.asarray(tail, dtype=float))) if tail else 0.0


def _count_prior_days(values: list[str], current: str, days: int) -> float:
    now = Date.fromisoformat(current)
    count = 0
    for raw in reversed(values):
        previous = Date.fromisoformat(raw)
        delta = (now - previous).days
        if delta <= 0:
            continue
        if delta > days:
            break
        count += 1
    return float(count)


def build_context_extras(
    games: list[dict[str, Any]],
) -> tuple[np.ndarray, list[str], list[str], list[int]]:
    """Build context features using only the prior-date state."""
    games = sorted(games, key=lambda row: (str(row["date"]), int(row["game_pk"])))
    scored: dict[int, list[float]] = defaultdict(list)
    allowed: dict[int, list[float]] = defaultdict(list)
    team_dates: dict[int, list[str]] = defaultdict(list)
    league_totals: list[float] = []
    league_home_margins: list[float] = []
    venue_totals: dict[int, list[float]] = defaultdict(list)
    rows: list[list[float]] = []
    dates: list[str] = []
    game_pks: list[int] = []

    for current_date, grouped in groupby(games, key=lambda row: str(row["date"])):
        day_games = list(grouped)
        league_30 = _mean_tail(league_totals, 30)
        league_100 = _mean_tail(league_totals, 100)
        league_margin_100 = _mean_tail(league_home_margins, 100)
        for game in day_games:
            home = int(game["home_id"]); away = int(game["away_id"])
            if len(scored[home]) < MIN_PRIOR or len(scored[away]) < MIN_PRIOR:
                continue
            venue_id = int(game.get("venue_id") or 0)
            prior_venue = venue_totals[venue_id] if venue_id else []
            if prior_venue and league_totals:
                venue_mean = _mean_tail(prior_venue, 100)
                league_reference = league_100
                weight = len(prior_venue[-100:]) / (len(prior_venue[-100:]) + PARK_SHRINK_GAMES)
                park_delta = (venue_mean - league_reference) * weight
            else:
                park_delta = 0.0
            rows.append([
                league_30,
                league_100,
                league_margin_100,
                float(park_delta),
                _count_prior_days(team_dates[home], current_date, 3),
                _count_prior_days(team_dates[away], current_date, 3),
                _mean_tail(allowed[home], 3),
                _mean_tail(allowed[away], 3),
            ])
            dates.append(current_date)
            game_pks.append(int(game["game_pk"]))

        # Same-date games never enter another game's feature state.
        for game in day_games:
            home = int(game["home_id"]); away = int(game["away_id"])
            home_score = float(game["home_score"]); away_score = float(game["away_score"])
            scored[home].append(home_score); allowed[home].append(away_score)
            scored[away].append(away_score); allowed[away].append(home_score)
            team_dates[home].append(current_date); team_dates[away].append(current_date)
            total = home_score + away_score
            league_totals.append(total)
            league_home_margins.append(home_score - away_score)
            venue_id = int(game.get("venue_id") or 0)
            if venue_id:
                venue_totals[venue_id].append(total)

    return np.asarray(rows, dtype=float), list(CONTEXT_FEATURE_NAMES), dates, game_pks


def build_v2_feature_sets(
    games: list[dict[str, Any]],
) -> tuple[dict[str, tuple[np.ndarray, list[str]]], np.ndarray, np.ndarray, list[str], list[int]]:
    feature_sets, margin, total, dates, game_pks = build_feature_sets(games)
    extras, extra_names, extra_dates, extra_game_pks = build_context_extras(games)
    if dates != extra_dates or game_pks != extra_game_pks:
        raise MLBDevelopmentV2Error("MLB_DEV_V2_ROW_IDENTITY_MISMATCH")
    if not np.isfinite(extras).all():
        raise MLBDevelopmentV2Error("MLB_DEV_V2_CONTEXT_NONFINITE")
    base_candidate, base_candidate_names = feature_sets["pit_multiwindow_v1"]
    feature_sets = dict(feature_sets)
    feature_sets["pit_context_v2"] = (
        np.column_stack([base_candidate, extras]),
        list(base_candidate_names) + extra_names,
    )
    return feature_sets, margin, total, dates, game_pks


def _matrix_sha256(matrix: np.ndarray) -> str:
    return _canonical_sha256([[float(value) for value in row] for row in matrix])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", default=",".join(str(year) for year in DEFAULT_SEASONS))
    parser.add_argument("--validation-season", type=int, default=DEFAULT_VALIDATION_SEASON)
    parser.add_argument("--out", default="artifacts/mlb_development_v2_report.json")
    args = parser.parse_args()

    try:
        seasons = [int(value) for value in args.seasons.split(",") if value.strip()]
        validate_development_window(seasons, args.validation_season)
    except (ValueError, Exception) as exc:
        # validate_development_window owns the stable error codes from V1.
        print(str(exc), file=sys.stderr)
        return 2
    if seasons != list(DEFAULT_SEASONS) or args.validation_season != DEFAULT_VALIDATION_SEASON:
        print("MLB_DEV_V2_REQUIRES_EXACT_2021_2024_WINDOW", file=sys.stderr)
        return 2

    games: list[dict[str, Any]] = []
    per_season: dict[int, int] = {}
    for season in seasons:
        if season > MAX_DEVELOPMENT_SEASON:
            print("MLB_DEV_V2_POST_2024_HTTP_FORBIDDEN", file=sys.stderr)
            return 2
        rows = fetch_season_with_venue(season)
        per_season[season] = len(rows)
        games.extend(rows)
        print(f"{season}: {len(rows)} final rows with venue metadata", flush=True)

    raw_games = sorted(games, key=lambda row: (str(row["date"]), int(row["game_pk"])))
    try:
        canonical_games, duplicate_normalization = _normalize_schedule_duplicates(raw_games)
        feature_sets, y_margin, y_total, dates, game_pks = build_v2_feature_sets(canonical_games)
    except (ValueError, MLBDevelopmentV2Error) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    valid_mask = np.asarray([date.startswith("2024") for date in dates])
    train_mask = ~valid_mask
    if int(valid_mask.sum()) < 200 or int(train_mask.sum()) < 500:
        print("MLB_DEV_V2_SPLIT_INSUFFICIENT", file=sys.stderr)
        return 2
    train_dates = [date for date, flag in zip(dates, train_mask) if bool(flag)]
    row_identity = [{"date": date, "game_pk": int(pk)} for date, pk in zip(dates, game_pks)]

    report: dict[str, Any] = {
        "schema": "MLB_DEVELOPMENT_V2_REPORT_V1",
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
        "source": "MLB StatsAPI free schedule/final-score endpoint plus venue fixture metadata; no odds provider",
        "fixture_metadata_limitation": "Historical venue identity is current StatsAPI fixture metadata, not an archived pregame snapshot; therefore this experiment is not promotion/PIT evidence.",
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
        },
        "hypothesis": {
            "predeclared_new_family": "pit_context_v2",
            "new_features": list(CONTEXT_FEATURE_NAMES),
            "rationale": "Test whether prior-only league run environment, shrunk prior-only venue scoring, and short schedule/run-prevention load add signal beyond the prior multi-window candidate.",
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
        baseline_rmse = target_result["feature_sets"]["baseline_v1"]["development_2024"]["rmse"]
        prior_rmse = target_result["feature_sets"]["pit_multiwindow_v1"]["development_2024"]["rmse"]
        context_rmse = target_result["feature_sets"]["pit_context_v2"]["development_2024"]["rmse"]
        target_result["comparisons"] = {
            "pit_multiwindow_minus_baseline_rmse": float(prior_rmse - baseline_rmse),
            "pit_context_v2_minus_baseline_rmse": float(context_rmse - baseline_rmse),
            "pit_context_v2_minus_pit_multiwindow_rmse": float(context_rmse - prior_rmse),
            "best_development_family": min(
                ("baseline_v1", "pit_multiwindow_v1", "pit_context_v2"),
                key=lambda name: target_result["feature_sets"][name]["development_2024"]["rmse"],
            ),
            "promotion_implication": "NONE_DEVELOPMENT_ONLY",
        }
        report["targets"][target_name] = target_result

    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    for target_name in ("margin", "total"):
        comparison = report["targets"][target_name]["comparisons"]
        print(
            f"{target_name}: best={comparison['best_development_family']} "
            f"context-vs-baseline={comparison['pit_context_v2_minus_baseline_rmse']:+.6f} "
            f"context-vs-prior={comparison['pit_context_v2_minus_pit_multiwindow_rmse']:+.6f}",
            flush=True,
        )
    print("RESEARCH ONLY / 2021-2024 DEVELOPMENT / 2025 NOT ACCESSED / NOT Model_P / NOT OFFICIAL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
