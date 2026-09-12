"""Walk-forward evidence for the isolated NFL M2 V2 discrete-score candidate.

The candidate is evaluated against the same closing no-vig M1 benchmark and the
same fold-safe isotonic calibration machinery as production M2, but its output is
diagnostic-only. Nothing in this module can alter the production registry.
"""
from __future__ import annotations

from math import isfinite, log
from typing import Any, Iterable

from sportsedge.core.walkforward.season import season_walk_forward
from .historical_validation import (
    build_calibration_evidence,
    calibrate_nfl_evaluations,
    no_vig_two_way,
)
from .m2_v2_candidate import (
    NFL_M2_V2_CANDIDATE_MODEL_ID,
    NFL_M2_V2_DISTRIBUTION_CONTRACT,
    derive_nfl_m2_v2_score_distribution,
    fit_nfl_m2_v2_candidate,
    price_nfl_m2_v2_game_markets,
)
from .m2_v2_selector import (
    DEFAULT_KERNEL_SCALE_GRID,
    NFL_M2_V2_SELECTOR_CONTRACT,
    select_nfl_m2_v2_kernel_scales,
)
from .m2 import NFL_M2_FEATURE_CONTRACT
from .production_validation import nflverse_spread_to_home_handicap

_EPS = 1e-9
_KEY_NUMBERS = (-7, -3, 3, 7)
_KEY_PROFILE_CONTRACT = "NFL_M2_V2_CANDIDATE_OOS_SIGNED_KEY_PMF_V1"


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _novig(a: Any, b: Any) -> tuple[float | None, float | None]:
    if a in (None, "") or b in (None, ""):
        return None, None
    try:
        return no_vig_two_way(a, b)
    except ValueError:
        return None, None


def _clip(value: float) -> float:
    return min(1.0 - _EPS, max(_EPS, float(value)))


def _conditional_probability(win: float, loss: float) -> float | None:
    denominator = float(win) + float(loss)
    if denominator <= 0.0 or not isfinite(denominator):
        return None
    return _clip(float(win) / denominator)


def _fixed_scale_selection(
    *,
    fold_train_seasons: Iterable[int],
    kernel_scale: float,
    scale_grid: Iterable[float],
) -> dict[str, Any]:
    return {
        "contract": NFL_M2_V2_SELECTOR_CONTRACT,
        "status": "DISABLED_FIXED_SCALE",
        "market_data_used": False,
        "outer_training_seasons": sorted({int(season) for season in fold_train_seasons}),
        "inner_test_seasons": [],
        "scale_grid": [float(value) for value in scale_grid],
        "evaluation_game_count": 0,
        "selected_margin_kernel_scale": float(kernel_scale),
        "selected_total_kernel_scale": float(kernel_scale),
        "selection_objective": None,
        "candidate_scores": [],
        "tie_break": "NOT_APPLICABLE_FIXED_SCALE",
    }


def _build_nfl_m2_v2_raw_evaluations_and_selection(
    rows: Iterable[dict[str, Any]],
    *,
    min_train_seasons: int = 2,
    ridge_alpha: float = 10.0,
    kernel_scale: float = 1.0,
    nested_kernel_scale_selection: bool = True,
    kernel_scale_grid: Iterable[float] = DEFAULT_KERNEL_SCALE_GRID,
    selector_min_inner_train_seasons: int = 2,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    data = [dict(row) for row in rows]
    if not data:
        return [], []
    grid = tuple(float(value) for value in kernel_scale_grid)
    folds = season_walk_forward(data, season_key="season", min_train_seasons=min_train_seasons)
    out: list[dict[str, Any]] = []
    selector_audits: list[dict[str, Any]] = []
    for fold in folds:
        fold_train_seasons = sorted({int(row["season"]) for row in fold.train_rows})
        if nested_kernel_scale_selection:
            selection = select_nfl_m2_v2_kernel_scales(
                fold.train_rows,
                ridge_alpha=ridge_alpha,
                scale_grid=grid,
                min_inner_train_seasons=selector_min_inner_train_seasons,
                fallback_scale=kernel_scale,
            )
        else:
            selection = _fixed_scale_selection(
                fold_train_seasons=fold_train_seasons,
                kernel_scale=kernel_scale,
                scale_grid=grid,
            )
        if bool(selection.get("market_data_used")):
            raise ValueError("NFL_M2_V2_SELECTOR_MARKET_DATA_PROHIBITED")
        if selection.get("outer_training_seasons") != fold_train_seasons:
            raise ValueError("NFL_M2_V2_SELECTOR_OUTER_TRAIN_IDENTITY_MISMATCH")

        margin_kernel_scale = float(selection["selected_margin_kernel_scale"])
        total_kernel_scale = float(selection["selected_total_kernel_scale"])
        model = fit_nfl_m2_v2_candidate(
            fold.train_rows,
            ridge_alpha=ridge_alpha,
            kernel_scale=kernel_scale,
            margin_kernel_scale=margin_kernel_scale,
            total_kernel_scale=total_kernel_scale,
        )
        if int(fold.test_season) in model.train_seasons:
            raise ValueError("NFL_M2_V2_TEST_SEASON_IN_TRAINING")
        selector_audits.append({
            "outer_test_season": int(fold.test_season),
            **selection,
        })

        for raw in fold.test_rows:
            row = dict(raw)
            distribution = derive_nfl_m2_v2_score_distribution(model, row)
            key_probabilities = {
                str(key): sum(
                    float(score["weight"])
                    for score in distribution
                    if int(score["margin"]) == key
                )
                for key in _KEY_NUMBERS
            }

            spread_line = _float(row.get("spread_line"))
            total_line = _float(row.get("total_line"))
            home_handicap = (
                nflverse_spread_to_home_handicap(spread_line)
                if spread_line is not None else None
            )
            candidate_home = None
            candidate_over = None
            if spread_line is not None or total_line is not None:
                pricing = price_nfl_m2_v2_game_markets(
                    distribution,
                    spread_line=home_handicap if home_handicap is not None else 0.0,
                    total_line=total_line if total_line is not None else 0.0,
                )
                if spread_line is not None:
                    candidate_home = _conditional_probability(
                        pricing["spread"]["home"], pricing["spread"]["away"]
                    )
                if total_line is not None:
                    candidate_over = _conditional_probability(
                        pricing["total"]["over"], pricing["total"]["under"]
                    )

            home_score = _float(row.get("home_score"))
            away_score = _float(row.get("away_score"))
            if home_score is None or away_score is None:
                raise ValueError("NFL_M2_V2_REALIZED_SCORE_MISSING")
            actual_margin = home_score - away_score
            actual_total = home_score + away_score
            spread_push = spread_line is not None and actual_margin == spread_line
            total_push = total_line is not None and actual_total == total_line
            home_cover = None if spread_line is None or spread_push else int(actual_margin > spread_line)
            over = None if total_line is None or total_push else int(actual_total > total_line)
            m1_home, _ = _novig(row.get("home_spread_odds"), row.get("away_spread_odds"))
            m1_over, _ = _novig(row.get("over_odds"), row.get("under_odds"))

            out.append({
                "game_id": str(row.get("game_id") or ""),
                "season": int(row["season"]),
                "week": row.get("week"),
                "model_id": model.model_id,
                "feature_contract": model.feature_contract,
                "distribution_contract": model.distribution_contract,
                "train_seasons": model.train_seasons,
                "ridge_alpha": model.mean_model.ridge_alpha,
                "kernel_scale": model.kernel_scale,
                "margin_kernel_scale": model.margin_kernel_scale,
                "total_kernel_scale": model.total_kernel_scale,
                "kernel_scale_selection_contract": selection["contract"],
                "kernel_scale_selection_status": selection["status"],
                "support_point_count": len(model.support_points),
                "weighted_support_size": len(distribution),
                "spread_line": spread_line,
                "home_handicap": home_handicap,
                "total_line": total_line,
                "spread_push": bool(spread_push),
                "total_push": bool(total_push),
                "home_cover_outcome": home_cover,
                "over_outcome": over,
                "m1_home_cover_prob": m1_home,
                "m1_over_prob": m1_over,
                # Reuse the generic fold-safe calibration field names only inside
                # this diagnostic payload. Candidate identity remains explicit.
                "m2_home_cover_prob": candidate_home,
                "m2_over_prob": candidate_over,
                "candidate_signed_key_probability": key_probabilities,
            })
    return out, selector_audits


def build_nfl_m2_v2_raw_evaluations(
    rows: Iterable[dict[str, Any]],
    *,
    min_train_seasons: int = 2,
    ridge_alpha: float = 10.0,
    kernel_scale: float = 1.0,
    nested_kernel_scale_selection: bool = True,
    kernel_scale_grid: Iterable[float] = DEFAULT_KERNEL_SCALE_GRID,
    selector_min_inner_train_seasons: int = 2,
) -> list[dict[str, Any]]:
    raw, _ = _build_nfl_m2_v2_raw_evaluations_and_selection(
        rows,
        min_train_seasons=min_train_seasons,
        ridge_alpha=ridge_alpha,
        kernel_scale=kernel_scale,
        nested_kernel_scale_selection=nested_kernel_scale_selection,
        kernel_scale_grid=kernel_scale_grid,
        selector_min_inner_train_seasons=selector_min_inner_train_seasons,
    )
    return raw


def _loss(pairs: list[tuple[int, float]]) -> tuple[float, float]:
    if not pairs:
        raise ValueError("NFL_M2_V2_EMPTY_EVALUATION")
    ll = 0.0
    brier = 0.0
    for outcome, probability in pairs:
        p = _clip(probability)
        ll += -(outcome * log(p) + (1 - outcome) * log(1.0 - p))
        brier += (p - outcome) ** 2
    return ll / len(pairs), brier / len(pairs)


def _fold_rows(evaluations: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    data = [dict(row) for row in evaluations]
    specs = {
        "spread": ("home_cover_outcome", "m1_home_cover_prob", "m2_home_cover_calibrated_prob"),
        "total": ("over_outcome", "m1_over_prob", "m2_over_calibrated_prob"),
    }
    output: list[dict[str, Any]] = []
    for season in sorted({int(row["season"]) for row in data}):
        season_rows = [row for row in data if int(row["season"]) == season]
        for market, (outcome_key, baseline_key, candidate_key) in specs.items():
            eligible = [
                row for row in season_rows
                if row.get(outcome_key) in (0, 1) and row.get(candidate_key) is not None
            ]
            comparable = [row for row in eligible if row.get(baseline_key) is not None]
            if not comparable:
                continue
            baseline_pairs = [
                (int(row[outcome_key]), float(row[baseline_key])) for row in comparable
            ]
            candidate_pairs = [
                (int(row[outcome_key]), float(row[candidate_key])) for row in comparable
            ]
            baseline_ll, baseline_brier = _loss(baseline_pairs)
            candidate_ll, candidate_brier = _loss(candidate_pairs)
            output.append({
                "season": season,
                "market": market,
                "n": len(comparable),
                "eligible_n": len(eligible),
                "m1_coverage": len(comparable) / len(eligible),
                "m1_log_loss": baseline_ll,
                "candidate_log_loss": candidate_ll,
                "m1_brier": baseline_brier,
                "candidate_brier": candidate_brier,
                "candidate_beats_m1": candidate_ll < baseline_ll,
                "candidate_probability_source": (
                    "TRAINING_EMPIRICAL_INTEGER_SCORE_SUPPORT_PLUS_FOLD_SAFE_ISOTONIC"
                ),
            })
    return output


def _key_profile(evaluations: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = [dict(row) for row in evaluations]
    if not rows:
        raise ValueError("NFL_M2_V2_KEY_PROFILE_EMPTY")
    totals = {key: 0.0 for key in _KEY_NUMBERS}
    for row in rows:
        payload = row.get("candidate_signed_key_probability")
        if not isinstance(payload, dict):
            raise ValueError("NFL_M2_V2_KEY_PROFILE_ROW_MISSING")
        for key in _KEY_NUMBERS:
            value = float(payload[str(key)])
            if not 0.0 <= value <= 1.0:
                raise ValueError("NFL_M2_V2_KEY_PROFILE_VALUE_INVALID")
            totals[key] += value
    n = float(len(rows))
    return {
        "contract": _KEY_PROFILE_CONTRACT,
        "model_id": NFL_M2_V2_CANDIDATE_MODEL_ID,
        "feature_contract": NFL_M2_FEATURE_CONTRACT,
        "distribution_contract": NFL_M2_V2_DISTRIBUTION_CONTRACT,
        "probability_source": "OOS_TRAINING_EMPIRICAL_INTEGER_SCORE_SUPPORT",
        "heldout_game_count": len(rows),
        "test_seasons": sorted({int(row["season"]) for row in rows}),
        "signed_key_probability": {
            str(key): totals[key] / n for key in _KEY_NUMBERS
        },
    }


def build_nfl_m2_v2_candidate_evidence(
    rows: Iterable[dict[str, Any]],
    *,
    source_manifest_sha256: str,
    min_train_seasons: int = 2,
    min_calibration_fit_seasons: int = 2,
    calibration_bins: int = 10,
    calibration_min_bin_n: int = 25,
    calibration_threshold: float = 0.05,
    fold_win_threshold: float = 0.65,
    ridge_alpha: float = 10.0,
    kernel_scale: float = 1.0,
    nested_kernel_scale_selection: bool = True,
    kernel_scale_grid: Iterable[float] = DEFAULT_KERNEL_SCALE_GRID,
    selector_min_inner_train_seasons: int = 2,
) -> dict[str, Any]:
    manifest = str(source_manifest_sha256 or "").strip().lower()
    if len(manifest) != 64:
        raise ValueError("NFL_M2_V2_SOURCE_MANIFEST_SHA256_INVALID")
    try:
        int(manifest, 16)
    except ValueError as exc:
        raise ValueError("NFL_M2_V2_SOURCE_MANIFEST_SHA256_INVALID") from exc

    grid = tuple(float(value) for value in kernel_scale_grid)
    raw, selector_audits = _build_nfl_m2_v2_raw_evaluations_and_selection(
        rows,
        min_train_seasons=min_train_seasons,
        ridge_alpha=ridge_alpha,
        kernel_scale=kernel_scale,
        nested_kernel_scale_selection=nested_kernel_scale_selection,
        kernel_scale_grid=grid,
        selector_min_inner_train_seasons=selector_min_inner_train_seasons,
    )
    calibrated = calibrate_nfl_evaluations(raw, min_fit_seasons=min_calibration_fit_seasons)
    folds = _fold_rows(calibrated)
    calibration = build_calibration_evidence(
        calibrated,
        bins=calibration_bins,
        min_bin_n=calibration_min_bin_n,
        max_bin_deviation_threshold=calibration_threshold,
    )
    per_market: dict[str, dict[str, Any]] = {}
    for market in ("spread", "total"):
        market_folds = [row for row in folds if row["market"] == market]
        wins = sum(bool(row["candidate_beats_m1"]) for row in market_folds)
        rate = wins / len(market_folds) if market_folds else 0.0
        per_market[market] = {
            "fold_wins": wins,
            "fold_total": len(market_folds),
            "fold_win_rate": rate,
            "required_fold_win_rate": float(fold_win_threshold),
            "historical_predictive_pass": bool(
                market_folds and rate >= float(fold_win_threshold)
            ),
            "calibration": calibration.get(market),
        }

    return {
        "schema_version": 1,
        "status": "DIAGNOSTIC_CANDIDATE_ONLY",
        "promotion_eligible": False,
        "model_id": NFL_M2_V2_CANDIDATE_MODEL_ID,
        "feature_contract": NFL_M2_FEATURE_CONTRACT,
        "distribution_contract": NFL_M2_V2_DISTRIBUTION_CONTRACT,
        "source_manifest_sha256": manifest,
        "raw_evaluation_count": len(raw),
        "fold_count": len(folds),
        "folds": folds,
        "calibration_evidence": calibration,
        "candidate_distribution_profile": _key_profile(raw),
        "candidate_historical_evidence": per_market,
        "nested_kernel_scale_selection": {
            "enabled": bool(nested_kernel_scale_selection),
            "contract": NFL_M2_V2_SELECTOR_CONTRACT,
            "outer_fold_audits": selector_audits,
        },
        "parameters": {
            "min_train_seasons": int(min_train_seasons),
            "min_calibration_fit_seasons": int(min_calibration_fit_seasons),
            "calibration_bins": int(calibration_bins),
            "calibration_min_bin_n": int(calibration_min_bin_n),
            "calibration_threshold": float(calibration_threshold),
            "fold_win_threshold": float(fold_win_threshold),
            "ridge_alpha": float(ridge_alpha),
            "kernel_scale": float(kernel_scale),
            "nested_kernel_scale_selection": bool(nested_kernel_scale_selection),
            "kernel_scale_grid": list(grid),
            "selector_min_inner_train_seasons": int(selector_min_inner_train_seasons),
        },
        "diagnostic_question": (
            "Does nested training-only selection of separate margin/total empirical-support "
            "bandwidths improve held-out spread/total evidence and signed 3/7 mass while the "
            "V1 market-blind mean predictor and frozen promotion gates remain unchanged?"
        ),
    }
