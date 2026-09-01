"""Walk-forward diagnostic evidence for the NFL M2 V2B candidate."""
from __future__ import annotations

from typing import Any, Iterable

from sportsedge.core.walkforward.season import season_walk_forward
from .historical_validation import build_calibration_evidence, calibrate_nfl_evaluations
from .m2 import NFL_M2_FEATURE_CONTRACT
from .m2_v2_candidate import price_nfl_m2_v2_game_markets
from .m2_v2_validation import _conditional_probability, _float, _fold_rows, _novig
from .m2_v2b_candidate import (
    NFL_M2_V2B_CANDIDATE_MODEL_ID,
    NFL_M2_V2B_DISTRIBUTION_CONTRACT,
    derive_nfl_m2_v2b_score_distribution,
    fit_nfl_m2_v2b_candidate,
)
from .production_validation import nflverse_spread_to_home_handicap

_KEY_NUMBERS = (-7, -3, 3, 7)
_KEY_PROFILE_CONTRACT = "NFL_M2_V2B_CANDIDATE_OOS_SIGNED_KEY_PMF_V1"


def build_nfl_m2_v2b_raw_evaluations(
    rows: Iterable[dict[str, Any]],
    *,
    min_train_seasons: int = 2,
    ridge_alpha: float = 10.0,
    kernel_scale: float = 1.0,
) -> list[dict[str, Any]]:
    data = [dict(row) for row in rows]
    if not data:
        return []
    folds = season_walk_forward(data, season_key="season", min_train_seasons=min_train_seasons)
    output: list[dict[str, Any]] = []
    for fold in folds:
        model = fit_nfl_m2_v2b_candidate(
            fold.train_rows,
            ridge_alpha=ridge_alpha,
            kernel_scale=kernel_scale,
        )
        if int(fold.test_season) in model.train_seasons:
            raise ValueError("NFL_M2_V2B_TEST_SEASON_IN_TRAINING")
        for raw in fold.test_rows:
            row = dict(raw)
            distribution = derive_nfl_m2_v2b_score_distribution(model, row)
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
                raise ValueError("NFL_M2_V2B_REALIZED_SCORE_MISSING")
            actual_margin = home_score - away_score
            actual_total = home_score + away_score
            spread_push = spread_line is not None and actual_margin == spread_line
            total_push = total_line is not None and actual_total == total_line
            home_cover = None if spread_line is None or spread_push else int(actual_margin > spread_line)
            over = None if total_line is None or total_push else int(actual_total > total_line)
            m1_home, _ = _novig(row.get("home_spread_odds"), row.get("away_spread_odds"))
            m1_over, _ = _novig(row.get("over_odds"), row.get("under_odds"))
            output.append({
                "game_id": str(row.get("game_id") or ""),
                "season": int(row["season"]),
                "week": row.get("week"),
                "model_id": model.model_id,
                "feature_contract": model.feature_contract,
                "distribution_contract": model.distribution_contract,
                "train_seasons": model.train_seasons,
                "ridge_alpha": model.mean_model.ridge_alpha,
                "kernel_scale": model.kernel_scale,
                "empirical_support_size": len(model.empirical_scores),
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
                "candidate_signed_key_probability": key_probabilities,
            })
    return output


def _key_profile(evaluations: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = [dict(row) for row in evaluations]
    if not rows:
        raise ValueError("NFL_M2_V2B_KEY_PROFILE_EMPTY")
    totals = {key: 0.0 for key in _KEY_NUMBERS}
    for row in rows:
        payload = row.get("candidate_signed_key_probability")
        if not isinstance(payload, dict):
            raise ValueError("NFL_M2_V2B_KEY_PROFILE_ROW_MISSING")
        for key in _KEY_NUMBERS:
            value = float(payload[str(key)])
            if not 0.0 <= value <= 1.0:
                raise ValueError("NFL_M2_V2B_KEY_PROFILE_VALUE_INVALID")
            totals[key] += value
    n = float(len(rows))
    return {
        "contract": _KEY_PROFILE_CONTRACT,
        "model_id": NFL_M2_V2B_CANDIDATE_MODEL_ID,
        "feature_contract": NFL_M2_FEATURE_CONTRACT,
        "distribution_contract": NFL_M2_V2B_DISTRIBUTION_CONTRACT,
        "probability_source": "OOS_EMPIRICAL_INTEGER_SCORE_RESIDUAL_LIKELIHOOD",
        "heldout_game_count": len(rows),
        "test_seasons": sorted({int(row["season"]) for row in rows}),
        "signed_key_probability": {str(key): totals[key] / n for key in _KEY_NUMBERS},
    }


def build_nfl_m2_v2b_candidate_evidence(
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
) -> dict[str, Any]:
    manifest = str(source_manifest_sha256 or "").strip().lower()
    if len(manifest) != 64:
        raise ValueError("NFL_M2_V2B_SOURCE_MANIFEST_SHA256_INVALID")
    try:
        int(manifest, 16)
    except ValueError as exc:
        raise ValueError("NFL_M2_V2B_SOURCE_MANIFEST_SHA256_INVALID") from exc

    raw = build_nfl_m2_v2b_raw_evaluations(
        rows,
        min_train_seasons=min_train_seasons,
        ridge_alpha=ridge_alpha,
        kernel_scale=kernel_scale,
    )
    calibrated = calibrate_nfl_evaluations(raw, min_fit_seasons=min_calibration_fit_seasons)
    folds = _fold_rows(calibrated)
    # Rename generic candidate keys so no diagnostic artifact can be mistaken for
    # production-M2 evidence simply because the shared calibration helper uses m2_* fields.
    for row in folds:
        row["candidate_log_loss"] = row.pop("candidate_log_loss", row.get("m2_log_loss"))
        row["candidate_brier"] = row.pop("candidate_brier", row.get("m2_brier"))
        row["candidate_beats_m1"] = row.pop("candidate_beats_m1", row.get("m2_beats_m1"))
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
        "model_id": NFL_M2_V2B_CANDIDATE_MODEL_ID,
        "feature_contract": NFL_M2_FEATURE_CONTRACT,
        "distribution_contract": NFL_M2_V2B_DISTRIBUTION_CONTRACT,
        "source_manifest_sha256": manifest,
        "raw_evaluation_count": len(raw),
        "fold_count": len(folds),
        "folds": folds,
        "calibration_evidence": calibration,
        "candidate_distribution_profile": _key_profile(raw),
        "candidate_historical_evidence": per_market,
        "parameters": {
            "min_train_seasons": int(min_train_seasons),
            "min_calibration_fit_seasons": int(min_calibration_fit_seasons),
            "calibration_bins": int(calibration_bins),
            "calibration_min_bin_n": int(calibration_min_bin_n),
            "calibration_threshold": float(calibration_threshold),
            "fold_win_threshold": float(fold_win_threshold),
            "ridge_alpha": float(ridge_alpha),
            "kernel_scale": float(kernel_scale),
        },
        "diagnostic_question": (
            "Does direct residual-likelihood conditioning on the empirical integer score lattice "
            "retain V2A key-number repair while improving held-out spread/total probabilities?"
        ),
    }
