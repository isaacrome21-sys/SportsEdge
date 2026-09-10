"""NFL M2 V2C diagnostic: nested training-only bandwidth selection.

V2C deliberately keeps V2A's market-blind empirical integer score support.  The
only experimental change is how ``kernel_scale`` is selected for each outer
walk-forward fold.  Selection uses earlier-season inner folds and realized score
errors only; sportsbook lines/prices, held-out outer outcomes, and frozen key-number
targets are never tuning inputs.

This module is diagnostic-only and cannot alter the production promotion registry.
"""
from __future__ import annotations

from math import isfinite, log
from typing import Any, Iterable, Sequence

from sportsedge.core.walkforward.season import season_walk_forward
from .historical_validation import (
    build_calibration_evidence,
    calibrate_nfl_evaluations,
    no_vig_two_way,
)
from .m2 import NFL_M2_FEATURE_CONTRACT
from .m2_v2_candidate import (
    derive_nfl_m2_v2_score_distribution,
    fit_nfl_m2_v2_candidate,
    price_nfl_m2_v2_game_markets,
)
from .production_validation import nflverse_spread_to_home_handicap

NFL_M2_V2C_CANDIDATE_MODEL_ID = "nfl_m2_discrete_score_support_nested_bandwidth_v2c_candidate"
NFL_M2_V2C_DISTRIBUTION_CONTRACT = "NFL_M2_V2C_EMPIRICAL_SCORE_SUPPORT_NESTED_BANDWIDTH_V1"
NFL_M2_V2C_TUNING_CONTRACT = "OUTER_TRAIN_ONLY_INNER_SEASON_SCORE_ERROR_V1"
_DEFAULT_GRID = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)
_KEY_NUMBERS = (-7, -3, 3, 7)
_EPS = 1e-9


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _clip(value: float) -> float:
    return min(1.0 - _EPS, max(_EPS, float(value)))


def _conditional_probability(win: float, loss: float) -> float | None:
    denominator = float(win) + float(loss)
    if denominator <= 0.0 or not isfinite(denominator):
        return None
    return _clip(float(win) / denominator)


def _novig(a: Any, b: Any) -> tuple[float | None, float | None]:
    if a in (None, "") or b in (None, ""):
        return None, None
    try:
        return no_vig_two_way(a, b)
    except ValueError:
        return None, None


def _grid(values: Sequence[float]) -> tuple[float, ...]:
    clean: set[float] = set()
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("NFL_M2_V2C_KERNEL_GRID_INVALID") from exc
        if not isfinite(number) or number <= 0.0:
            raise ValueError("NFL_M2_V2C_KERNEL_GRID_INVALID")
        clean.add(number)
    if not clean:
        raise ValueError("NFL_M2_V2C_KERNEL_GRID_EMPTY")
    return tuple(sorted(clean))


def _expected_margin_total(distribution: Iterable[dict[str, Any]]) -> tuple[float, float]:
    rows = [dict(row) for row in distribution]
    if not rows:
        raise ValueError("NFL_M2_V2C_DISTRIBUTION_EMPTY")
    weight = sum(float(row["weight"]) for row in rows)
    if not isfinite(weight) or abs(weight - 1.0) > 1e-8:
        raise ValueError("NFL_M2_V2C_DISTRIBUTION_WEIGHT_INVALID")
    margin = sum(float(row["margin"]) * float(row["weight"]) for row in rows)
    total = sum(float(row["total"]) * float(row["weight"]) for row in rows)
    return margin, total


def select_v2c_kernel_scale(
    outer_train_rows: Iterable[dict[str, Any]],
    *,
    ridge_alpha: float = 10.0,
    kernel_grid: Sequence[float] = _DEFAULT_GRID,
    inner_min_train_seasons: int = 1,
) -> dict[str, Any]:
    """Select a bandwidth without inspecting the outer holdout or betting markets.

    The objective is the mean squared error of the inner-fold expected margin and
    total, each normalized by the fold's training residual sigma.  Only realized
    scores from inner validation seasons are used.  Root sportsbook fields may be
    present in the row container but are never read by this function.
    """
    rows = [dict(row) for row in outer_train_rows]
    if not rows:
        raise ValueError("NFL_M2_V2C_TUNING_ROWS_REQUIRED")
    grid = _grid(kernel_grid)
    folds = season_walk_forward(rows, season_key="season", min_train_seasons=inner_min_train_seasons)
    if not folds:
        raise ValueError("NFL_M2_V2C_INNER_FOLDS_REQUIRED")

    scores: list[dict[str, Any]] = []
    for scale in grid:
        loss_sum = 0.0
        n = 0
        fold_scores: list[dict[str, Any]] = []
        for fold in folds:
            model = fit_nfl_m2_v2_candidate(
                fold.train_rows,
                ridge_alpha=ridge_alpha,
                kernel_scale=scale,
            )
            if int(fold.test_season) in model.train_seasons:
                raise ValueError("NFL_M2_V2C_INNER_TEST_SEASON_IN_TRAINING")
            margin_sigma = max(float(model.mean_model.margin_sigma), 1e-9)
            total_sigma = max(float(model.mean_model.total_sigma), 1e-9)
            fold_loss = 0.0
            fold_n = 0
            for raw in fold.test_rows:
                row = dict(raw)
                home = _float(row.get("home_score")); away = _float(row.get("away_score"))
                if home is None or away is None:
                    raise ValueError("NFL_M2_V2C_REALIZED_SCORE_MISSING")
                distribution = derive_nfl_m2_v2_score_distribution(model, row)
                expected_margin, expected_total = _expected_margin_total(distribution)
                actual_margin = home - away
                actual_total = home + away
                error = ((expected_margin - actual_margin) / margin_sigma) ** 2
                error += ((expected_total - actual_total) / total_sigma) ** 2
                fold_loss += error
                fold_n += 1
            if fold_n:
                fold_scores.append({
                    "test_season": int(fold.test_season),
                    "train_seasons": tuple(int(value) for value in fold.train_seasons),
                    "n": fold_n,
                    "mean_normalized_score_error": fold_loss / fold_n,
                })
                loss_sum += fold_loss
                n += fold_n
        if not n:
            raise ValueError("NFL_M2_V2C_TUNING_EVALUATIONS_EMPTY")
        scores.append({
            "kernel_scale": scale,
            "n": n,
            "mean_normalized_score_error": loss_sum / n,
            "inner_folds": fold_scores,
        })

    # Deterministic tie-break: prefer a scale closest to the V2A baseline 1.0,
    # then the numerically smaller scale.  No held-out or market information is
    # consulted here.
    winner = min(
        scores,
        key=lambda item: (
            float(item["mean_normalized_score_error"]),
            abs(log(float(item["kernel_scale"]))),
            float(item["kernel_scale"]),
        ),
    )
    return {
        "tuning_contract": NFL_M2_V2C_TUNING_CONTRACT,
        "selected_kernel_scale": float(winner["kernel_scale"]),
        "objective": "NORMALIZED_MARGIN_TOTAL_EXPECTATION_MSE",
        "inner_min_train_seasons": int(inner_min_train_seasons),
        "outer_train_seasons": sorted({int(row["season"]) for row in rows}),
        "candidate_scores": scores,
        "market_fields_used_for_tuning": False,
        "key_number_targets_used_for_tuning": False,
        "outer_holdout_used_for_tuning": False,
    }


def build_nfl_m2_v2c_raw_evaluations(
    rows: Iterable[dict[str, Any]],
    *,
    min_train_seasons: int = 2,
    inner_min_train_seasons: int = 1,
    ridge_alpha: float = 10.0,
    kernel_grid: Sequence[float] = _DEFAULT_GRID,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    data = [dict(row) for row in rows]
    if not data:
        return [], []
    folds = season_walk_forward(data, season_key="season", min_train_seasons=min_train_seasons)
    out: list[dict[str, Any]] = []
    tuning: list[dict[str, Any]] = []
    for fold in folds:
        selection = select_v2c_kernel_scale(
            fold.train_rows,
            ridge_alpha=ridge_alpha,
            kernel_grid=kernel_grid,
            inner_min_train_seasons=inner_min_train_seasons,
        )
        scale = float(selection["selected_kernel_scale"])
        selection = dict(selection)
        selection["outer_test_season"] = int(fold.test_season)
        tuning.append(selection)
        model = fit_nfl_m2_v2_candidate(fold.train_rows, ridge_alpha=ridge_alpha, kernel_scale=scale)
        if int(fold.test_season) in model.train_seasons:
            raise ValueError("NFL_M2_V2C_OUTER_TEST_SEASON_IN_TRAINING")
        for raw in fold.test_rows:
            row = dict(raw)
            distribution = derive_nfl_m2_v2_score_distribution(model, row)
            key_probabilities = {
                str(key): sum(float(score["weight"]) for score in distribution if int(score["margin"]) == key)
                for key in _KEY_NUMBERS
            }
            spread_line = _float(row.get("spread_line")); total_line = _float(row.get("total_line"))
            home_handicap = nflverse_spread_to_home_handicap(spread_line) if spread_line is not None else None
            candidate_home = None; candidate_over = None
            if spread_line is not None or total_line is not None:
                pricing = price_nfl_m2_v2_game_markets(
                    distribution,
                    spread_line=home_handicap if home_handicap is not None else 0.0,
                    total_line=total_line if total_line is not None else 0.0,
                )
                if spread_line is not None:
                    candidate_home = _conditional_probability(pricing["spread"]["home"], pricing["spread"]["away"])
                if total_line is not None:
                    candidate_over = _conditional_probability(pricing["total"]["over"], pricing["total"]["under"])
            home_score = _float(row.get("home_score")); away_score = _float(row.get("away_score"))
            if home_score is None or away_score is None:
                raise ValueError("NFL_M2_V2C_REALIZED_SCORE_MISSING")
            actual_margin = home_score - away_score; actual_total = home_score + away_score
            spread_push = spread_line is not None and actual_margin == spread_line
            total_push = total_line is not None and actual_total == total_line
            m1_home, _ = _novig(row.get("home_spread_odds"), row.get("away_spread_odds"))
            m1_over, _ = _novig(row.get("over_odds"), row.get("under_odds"))
            out.append({
                "game_id": str(row.get("game_id") or ""), "season": int(row["season"]), "week": row.get("week"),
                "model_id": NFL_M2_V2C_CANDIDATE_MODEL_ID, "feature_contract": NFL_M2_FEATURE_CONTRACT,
                "distribution_contract": NFL_M2_V2C_DISTRIBUTION_CONTRACT,
                "tuning_contract": NFL_M2_V2C_TUNING_CONTRACT, "train_seasons": model.train_seasons,
                "ridge_alpha": model.mean_model.ridge_alpha, "kernel_scale": scale,
                "support_point_count": len(model.support_points), "weighted_support_size": len(distribution),
                "spread_line": spread_line, "home_handicap": home_handicap, "total_line": total_line,
                "spread_push": bool(spread_push), "total_push": bool(total_push),
                "home_cover_outcome": None if spread_line is None or spread_push else int(actual_margin > spread_line),
                "over_outcome": None if total_line is None or total_push else int(actual_total > total_line),
                "m1_home_cover_prob": m1_home, "m1_over_prob": m1_over,
                "m2_home_cover_prob": candidate_home, "m2_over_prob": candidate_over,
                "candidate_signed_key_probability": key_probabilities,
            })
    return out, tuning


def _loss(pairs: list[tuple[int, float]]) -> float:
    if not pairs:
        raise ValueError("NFL_M2_V2C_EMPTY_EVALUATION")
    total = 0.0
    for outcome, probability in pairs:
        p = _clip(probability)
        total += -(outcome * log(p) + (1 - outcome) * log(1.0 - p))
    return total / len(pairs)


def _fold_rows(evaluations: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    data = [dict(row) for row in evaluations]
    specs = {
        "spread": ("home_cover_outcome", "m1_home_cover_prob", "m2_home_cover_calibrated_prob"),
        "total": ("over_outcome", "m1_over_prob", "m2_over_calibrated_prob"),
    }
    out: list[dict[str, Any]] = []
    for season in sorted({int(row["season"]) for row in data}):
        season_rows = [row for row in data if int(row["season"]) == season]
        for market, (outcome_key, baseline_key, candidate_key) in specs.items():
            comparable = [
                row for row in season_rows
                if row.get(outcome_key) in (0, 1) and row.get(candidate_key) is not None and row.get(baseline_key) is not None
            ]
            if not comparable:
                continue
            baseline = _loss([(int(row[outcome_key]), float(row[baseline_key])) for row in comparable])
            candidate = _loss([(int(row[outcome_key]), float(row[candidate_key])) for row in comparable])
            out.append({
                "season": season, "market": market, "n": len(comparable),
                "m1_log_loss": baseline, "candidate_log_loss": candidate,
                "candidate_beats_m1": candidate < baseline,
            })
    return out


def _key_profile(evaluations: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = [dict(row) for row in evaluations]
    if not rows:
        raise ValueError("NFL_M2_V2C_KEY_PROFILE_EMPTY")
    totals = {key: 0.0 for key in _KEY_NUMBERS}
    for row in rows:
        payload = row.get("candidate_signed_key_probability")
        if not isinstance(payload, dict):
            raise ValueError("NFL_M2_V2C_KEY_PROFILE_ROW_MISSING")
        for key in _KEY_NUMBERS:
            totals[key] += float(payload[str(key)])
    n = float(len(rows))
    return {
        "model_id": NFL_M2_V2C_CANDIDATE_MODEL_ID,
        "distribution_contract": NFL_M2_V2C_DISTRIBUTION_CONTRACT,
        "tuning_contract": NFL_M2_V2C_TUNING_CONTRACT,
        "probability_source": "OOS_TRAINING_EMPIRICAL_INTEGER_SCORE_SUPPORT_NESTED_BANDWIDTH",
        "heldout_game_count": len(rows),
        "signed_key_probability": {str(key): totals[key] / n for key in _KEY_NUMBERS},
    }


def build_nfl_m2_v2c_candidate_evidence(
    rows: Iterable[dict[str, Any]],
    *,
    source_manifest_sha256: str,
    min_train_seasons: int = 2,
    inner_min_train_seasons: int = 1,
    min_calibration_fit_seasons: int = 2,
    calibration_bins: int = 10,
    calibration_min_bin_n: int = 25,
    calibration_threshold: float = 0.05,
    fold_win_threshold: float = 0.65,
    ridge_alpha: float = 10.0,
    kernel_grid: Sequence[float] = _DEFAULT_GRID,
) -> dict[str, Any]:
    manifest = str(source_manifest_sha256 or "").strip().lower()
    if len(manifest) != 64:
        raise ValueError("NFL_M2_V2C_SOURCE_MANIFEST_SHA256_INVALID")
    try:
        int(manifest, 16)
    except ValueError as exc:
        raise ValueError("NFL_M2_V2C_SOURCE_MANIFEST_SHA256_INVALID") from exc
    raw, tuning = build_nfl_m2_v2c_raw_evaluations(
        rows, min_train_seasons=min_train_seasons, inner_min_train_seasons=inner_min_train_seasons,
        ridge_alpha=ridge_alpha, kernel_grid=kernel_grid,
    )
    calibrated = calibrate_nfl_evaluations(raw, min_fit_seasons=min_calibration_fit_seasons)
    folds = _fold_rows(calibrated)
    calibration = build_calibration_evidence(
        calibrated, bins=calibration_bins, min_bin_n=calibration_min_bin_n,
        max_bin_deviation_threshold=calibration_threshold,
    )
    markets: dict[str, Any] = {}
    for market in ("spread", "total"):
        subset = [row for row in folds if row["market"] == market]
        wins = sum(bool(row["candidate_beats_m1"]) for row in subset)
        rate = wins / len(subset) if subset else 0.0
        markets[market] = {
            "fold_wins": wins, "fold_total": len(subset), "fold_win_rate": rate,
            "required_fold_win_rate": float(fold_win_threshold),
            "historical_predictive_pass": bool(subset and rate >= float(fold_win_threshold)),
            "calibration": calibration.get(market),
        }
    return {
        "schema_version": 1, "status": "DIAGNOSTIC_CANDIDATE_ONLY", "promotion_eligible": False,
        "model_id": NFL_M2_V2C_CANDIDATE_MODEL_ID, "feature_contract": NFL_M2_FEATURE_CONTRACT,
        "distribution_contract": NFL_M2_V2C_DISTRIBUTION_CONTRACT,
        "tuning_contract": NFL_M2_V2C_TUNING_CONTRACT,
        "source_manifest_sha256": manifest, "raw_evaluation_count": len(raw), "folds": folds,
        "calibration_evidence": calibration, "candidate_distribution_profile": _key_profile(raw),
        "candidate_historical_evidence": markets, "outer_fold_tuning": tuning,
        "parameters": {
            "min_train_seasons": int(min_train_seasons), "inner_min_train_seasons": int(inner_min_train_seasons),
            "min_calibration_fit_seasons": int(min_calibration_fit_seasons), "ridge_alpha": float(ridge_alpha),
            "kernel_grid": list(_grid(kernel_grid)), "fold_win_threshold": float(fold_win_threshold),
        },
        "governance": {
            "market_fields_used_for_tuning": False, "key_number_targets_used_for_tuning": False,
            "outer_holdout_used_for_tuning": False, "production_registry_changed": False,
        },
    }


__all__ = [
    "NFL_M2_V2C_CANDIDATE_MODEL_ID", "NFL_M2_V2C_DISTRIBUTION_CONTRACT", "NFL_M2_V2C_TUNING_CONTRACT",
    "build_nfl_m2_v2c_candidate_evidence", "build_nfl_m2_v2c_raw_evaluations", "select_v2c_kernel_scale",
]
