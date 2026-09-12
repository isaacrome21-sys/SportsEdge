"""Walk-forward evidence for the NFL M2 V2C split-mean diagnostic.

V2C is research-only. Each outer fold chooses margin/total ridge penalties from
inner training seasons only, then scores the untouched outer season. Sportsbook
fields are applied only after the market-blind score distribution exists.
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Iterable

from sportsedge.core.walkforward.season import season_walk_forward
from .historical_validation import build_calibration_evidence, calibrate_nfl_evaluations, no_vig_two_way
from .m2 import NFL_M2_FEATURE_CONTRACT, price_nfl_m2_game_markets
from .m2_v2_validation import _fold_rows
from .m2_v2c_candidate import (
    NFL_M2_V2C_CANDIDATE_MODEL_ID,
    NFL_M2_V2C_DISTRIBUTION_CONTRACT,
    derive_nfl_m2_v2c_score_distribution,
    fit_nfl_m2_v2c_candidate,
)
from .m2_v2c_selector import DEFAULT_ALPHA_GRID, NFL_M2_V2C_SELECTOR_CONTRACT, select_nfl_m2_v2c_alphas
from .production_validation import nflverse_spread_to_home_handicap

_KEY_NUMBERS = (-7, -3, 3, 7)
_KEY_PROFILE_CONTRACT = "NFL_M2_V2C_OOS_SIGNED_KEY_PMF_V1"


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


def _conditional_probability(win: float, loss: float) -> float | None:
    denom = float(win) + float(loss)
    if denom <= 0.0 or not isfinite(denom):
        return None
    return min(1.0 - 1e-9, max(1e-9, float(win) / denom))


def _build_raw_and_selection(
    rows: Iterable[dict[str, Any]],
    *,
    min_train_seasons: int = 2,
    alpha_grid: Iterable[float] = DEFAULT_ALPHA_GRID,
    fallback_alpha: float = 10.0,
    selector_min_inner_train_seasons: int = 2,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    data = [dict(row) for row in rows]
    if not data:
        return [], []
    grid = tuple(float(value) for value in alpha_grid)
    folds = season_walk_forward(data, season_key="season", min_train_seasons=min_train_seasons)
    out: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []

    for fold in folds:
        train_seasons = sorted({int(row["season"]) for row in fold.train_rows})
        selection = select_nfl_m2_v2c_alphas(
            fold.train_rows,
            alpha_grid=grid,
            min_inner_train_seasons=selector_min_inner_train_seasons,
            fallback_alpha=fallback_alpha,
        )
        if bool(selection.get("market_data_used")):
            raise ValueError("NFL_M2_V2C_SELECTOR_MARKET_DATA_PROHIBITED")
        if selection.get("outer_training_seasons") != train_seasons:
            raise ValueError("NFL_M2_V2C_SELECTOR_OUTER_TRAIN_IDENTITY_MISMATCH")
        inner = {int(season) for season in selection.get("inner_test_seasons", [])}
        if not inner.issubset(set(train_seasons)):
            raise ValueError("NFL_M2_V2C_SELECTOR_INNER_TEST_OUTSIDE_OUTER_TRAIN")
        if int(fold.test_season) in inner:
            raise ValueError("NFL_M2_V2C_SELECTOR_OUTER_TEST_LEAKAGE")

        margin_alpha = float(selection["selected_margin_ridge_alpha"])
        total_alpha = float(selection["selected_total_ridge_alpha"])
        model = fit_nfl_m2_v2c_candidate(
            fold.train_rows,
            margin_ridge_alpha=margin_alpha,
            total_ridge_alpha=total_alpha,
        )
        if int(fold.test_season) in model.train_seasons:
            raise ValueError("NFL_M2_V2C_TEST_SEASON_IN_TRAINING")
        audits.append({"outer_test_season": int(fold.test_season), **selection})

        for raw in fold.test_rows:
            row = dict(raw)
            distribution = derive_nfl_m2_v2c_score_distribution(model, row)
            n = float(len(distribution))
            key_probs = {
                str(key): sum(int(score["margin"]) == key for score in distribution) / n
                for key in _KEY_NUMBERS
            }
            spread_line = _float(row.get("spread_line"))
            total_line = _float(row.get("total_line"))
            home_handicap = nflverse_spread_to_home_handicap(spread_line) if spread_line is not None else None
            candidate_home = None
            candidate_over = None
            if spread_line is not None or total_line is not None:
                priced = price_nfl_m2_game_markets(
                    distribution,
                    spread_line=home_handicap if home_handicap is not None else 0.0,
                    total_line=total_line if total_line is not None else 0.0,
                )
                if spread_line is not None:
                    candidate_home = _conditional_probability(priced["spread"]["home"], priced["spread"]["away"])
                if total_line is not None:
                    candidate_over = _conditional_probability(priced["total"]["over"], priced["total"]["under"])

            home_score = _float(row.get("home_score"))
            away_score = _float(row.get("away_score"))
            if home_score is None or away_score is None:
                raise ValueError("NFL_M2_V2C_REALIZED_SCORE_MISSING")
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
                "feature_contract": NFL_M2_FEATURE_CONTRACT,
                "distribution_contract": model.distribution_contract,
                "train_seasons": model.train_seasons,
                "margin_ridge_alpha": model.margin_ridge_alpha,
                "total_ridge_alpha": model.total_ridge_alpha,
                "alpha_selection_contract": selection["contract"],
                "alpha_selection_status": selection["status"],
                "spread_line": spread_line,
                "home_handicap": home_handicap,
                "total_line": total_line,
                "spread_push": bool(spread_push),
                "total_push": bool(total_push),
                "home_cover_outcome": home_cover,
                "over_outcome": over,
                "m1_home_cover_prob": m1_home,
                "m1_over_prob": m1_over,
                "m2_home_cover_prob": candidate_home,
                "m2_over_prob": candidate_over,
                "candidate_signed_key_probability": key_probs,
            })
    return out, audits


def build_nfl_m2_v2c_raw_evaluations(rows: Iterable[dict[str, Any]], **kwargs: Any) -> list[dict[str, Any]]:
    raw, _ = _build_raw_and_selection(rows, **kwargs)
    return raw


def _key_profile(raw: list[dict[str, Any]]) -> dict[str, Any]:
    if not raw:
        raise ValueError("NFL_M2_V2C_KEY_PROFILE_EMPTY")
    totals = {key: 0.0 for key in _KEY_NUMBERS}
    for row in raw:
        payload = row["candidate_signed_key_probability"]
        for key in _KEY_NUMBERS:
            totals[key] += float(payload[str(key)])
    n = float(len(raw))
    return {
        "contract": _KEY_PROFILE_CONTRACT,
        "model_id": NFL_M2_V2C_CANDIDATE_MODEL_ID,
        "feature_contract": NFL_M2_FEATURE_CONTRACT,
        "distribution_contract": NFL_M2_V2C_DISTRIBUTION_CONTRACT,
        "probability_source": "OOS_SPLIT_RIDGE_PAIRED_TRAINING_RESIDUAL_REPLAY",
        "heldout_game_count": len(raw),
        "test_seasons": sorted({int(row["season"]) for row in raw}),
        "signed_key_probability": {str(key): totals[key] / n for key in _KEY_NUMBERS},
    }


def build_nfl_m2_v2c_candidate_evidence(
    rows: Iterable[dict[str, Any]],
    *,
    source_manifest_sha256: str,
    min_train_seasons: int = 2,
    min_calibration_fit_seasons: int = 2,
    calibration_bins: int = 10,
    calibration_min_bin_n: int = 25,
    calibration_threshold: float = 0.05,
    fold_win_threshold: float = 0.65,
    alpha_grid: Iterable[float] = DEFAULT_ALPHA_GRID,
    fallback_alpha: float = 10.0,
    selector_min_inner_train_seasons: int = 2,
) -> dict[str, Any]:
    manifest = str(source_manifest_sha256 or "").strip().lower()
    if len(manifest) != 64:
        raise ValueError("NFL_M2_V2C_SOURCE_MANIFEST_SHA256_INVALID")
    try:
        int(manifest, 16)
    except ValueError as exc:
        raise ValueError("NFL_M2_V2C_SOURCE_MANIFEST_SHA256_INVALID") from exc
    grid = tuple(float(value) for value in alpha_grid)
    raw, audits = _build_raw_and_selection(
        rows,
        min_train_seasons=min_train_seasons,
        alpha_grid=grid,
        fallback_alpha=fallback_alpha,
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
            "historical_predictive_pass": bool(market_folds and rate >= float(fold_win_threshold)),
            "calibration": calibration.get(market),
        }
    return {
        "schema_version": 1,
        "status": "DIAGNOSTIC_CANDIDATE_ONLY",
        "promotion_eligible": False,
        "model_id": NFL_M2_V2C_CANDIDATE_MODEL_ID,
        "feature_contract": NFL_M2_FEATURE_CONTRACT,
        "distribution_contract": NFL_M2_V2C_DISTRIBUTION_CONTRACT,
        "source_manifest_sha256": manifest,
        "raw_evaluation_count": len(raw),
        "fold_count": len(folds),
        "folds": folds,
        "calibration_evidence": calibration,
        "candidate_distribution_profile": _key_profile(raw),
        "candidate_historical_evidence": per_market,
        "split_alpha_selection": {
            "enabled": True,
            "contract": NFL_M2_V2C_SELECTOR_CONTRACT,
            "outer_fold_audits": audits,
        },
        "parameters": {
            "min_train_seasons": int(min_train_seasons),
            "min_calibration_fit_seasons": int(min_calibration_fit_seasons),
            "calibration_threshold": float(calibration_threshold),
            "fold_win_threshold": float(fold_win_threshold),
            "fallback_alpha": float(fallback_alpha),
            "alpha_grid": list(grid),
            "selector_min_inner_train_seasons": int(selector_min_inner_train_seasons),
        },
        "diagnostic_question": "Do independently selected training-only margin/total ridge penalties improve untouched outer-fold spread/total evidence without market leakage?",
    }
