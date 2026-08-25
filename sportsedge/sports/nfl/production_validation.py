"""Exact production-NFL-M2 walk-forward evidence producer.

This module is the bridge between point-in-time market-blind M2 feature rows and
promotion evidence. It fits the exact production ridge model on prior seasons,
derives a joint score distribution from paired train residuals, and only then
applies closing spread/total thresholds. Fold-safe isotonic calibration is fit on
prior out-of-sample seasons only.
"""
from __future__ import annotations

from dataclasses import asdict
from math import log
from typing import Any, Iterable

from sportsedge.core.validation.football_evidence import FootballValidationBundle, build_promotion_evidence, validate_real_history_bundle
from sportsedge.core.walkforward.season import season_walk_forward
from sportsedge.sports.nfl.historical_validation import build_calibration_evidence, calibrate_nfl_evaluations, no_vig_two_way
from sportsedge.sports.nfl.m2 import (
    NFL_M2_FEATURE_CONTRACT, PRODUCTION_NFL_M2_MODEL_ID,
    derive_nfl_m2_score_distribution, fit_nfl_m2_score_model, price_nfl_m2_game_markets,
)

_EPS = 1e-9


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sha256(value: Any, error: str) -> str:
    raw = str(value or "").strip().lower()
    if len(raw) != 64:
        raise ValueError(error)
    try:
        int(raw, 16)
    except ValueError as exc:
        raise ValueError(error) from exc
    return raw


def _novig(a: Any, b: Any) -> tuple[float | None, float | None]:
    if a in (None, "") or b in (None, ""):
        return None, None
    try:
        return no_vig_two_way(a, b)
    except ValueError:
        return None, None


def _empirical_binary_probability(win_probability: float, loss_probability: float, n: int) -> float | None:
    """Jeffreys-smoothed conditional win probability after push removal."""
    if n <= 0:
        return None
    win = int(round(float(win_probability) * n)); loss = int(round(float(loss_probability) * n))
    if win + loss <= 0:
        return None
    return (win + 0.5) / (win + loss + 1.0)


def build_production_nfl_raw_evaluations(
    rows: Iterable[dict[str, Any]], *, min_train_seasons: int = 2, ridge_alpha: float = 10.0,
) -> list[dict[str, Any]]:
    """Fit exact production M2 per fold and emit uncalibrated market evaluations."""
    data = [dict(row) for row in rows]
    if not data:
        return []
    folds = season_walk_forward(data, season_key="season", min_train_seasons=min_train_seasons)
    out: list[dict[str, Any]] = []
    for fold in folds:
        model = fit_nfl_m2_score_model(fold.train_rows, ridge_alpha=ridge_alpha)
        if int(fold.test_season) in model.train_seasons:
            raise ValueError("NFL_PRODUCTION_VALIDATION_TEST_SEASON_IN_TRAINING")
        for raw in fold.test_rows:
            row = dict(raw); distribution = derive_nfl_m2_score_distribution(model, row); n = len(distribution)
            spread_line = _float(row.get("spread_line")); total_line = _float(row.get("total_line"))
            m2_home = None; m2_over = None
            if spread_line is not None and total_line is not None:
                pricing = price_nfl_m2_game_markets(distribution, spread_line=spread_line, total_line=total_line)
                m2_home = _empirical_binary_probability(pricing["spread"]["home"], pricing["spread"]["away"], n)
                m2_over = _empirical_binary_probability(pricing["total"]["over"], pricing["total"]["under"], n)

            home_score = _float(row.get("home_score")); away_score = _float(row.get("away_score"))
            if home_score is None or away_score is None:
                raise ValueError("NFL_PRODUCTION_VALIDATION_REALIZED_SCORE_MISSING")
            actual_margin = home_score - away_score; actual_total = home_score + away_score
            spread_push = spread_line is not None and actual_margin == spread_line
            total_push = total_line is not None and actual_total == total_line
            home_cover = None if spread_line is None or spread_push else int(actual_margin > spread_line)
            over = None if total_line is None or total_push else int(actual_total > total_line)
            m1_home, _ = _novig(row.get("home_spread_odds"), row.get("away_spread_odds"))
            m1_over, _ = _novig(row.get("over_odds"), row.get("under_odds"))
            out.append({
                "game_id": str(row.get("game_id") or ""), "season": int(row["season"]), "week": row.get("week"),
                "model_id": model.model_id, "feature_contract": model.feature_contract,
                "train_seasons": model.train_seasons, "ridge_alpha": model.ridge_alpha,
                "residual_distribution_n": n, "margin_sigma": model.margin_sigma,
                "total_sigma": model.total_sigma, "residual_correlation": model.residual_correlation,
                "spread_line": spread_line, "total_line": total_line, "spread_push": bool(spread_push),
                "total_push": bool(total_push), "home_cover_outcome": home_cover, "over_outcome": over,
                "m1_home_cover_prob": m1_home, "m1_over_prob": m1_over,
                "m2_home_cover_prob": m2_home, "m2_over_prob": m2_over,
            })
    return out


def _clip(value: float) -> float:
    return min(1.0 - _EPS, max(_EPS, float(value)))


def _log_loss(pairs: list[tuple[int, float]]) -> float:
    if not pairs:
        raise ValueError("NFL_PRODUCTION_VALIDATION_EMPTY_LOG_LOSS")
    return sum(-(y * log(_clip(p)) + (1 - y) * log(1.0 - _clip(p))) for y, p in pairs) / len(pairs)


def _brier(pairs: list[tuple[int, float]]) -> float:
    if not pairs:
        raise ValueError("NFL_PRODUCTION_VALIDATION_EMPTY_BRIER")
    return sum((_clip(p) - y) ** 2 for y, p in pairs) / len(pairs)


def _folds_with_brier(evaluations: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    data = [dict(row) for row in evaluations]
    specs = {
        "spread": ("home_cover_outcome", "m1_home_cover_prob", "m2_home_cover_calibrated_prob"),
        "total": ("over_outcome", "m1_over_prob", "m2_over_calibrated_prob"),
    }
    folds: list[dict[str, Any]] = []
    for season in sorted({int(row["season"]) for row in data}):
        season_rows = [row for row in data if int(row["season"]) == season]
        for market, (outcome_key, m1_key, m2_key) in specs.items():
            eligible = [row for row in season_rows if row.get(outcome_key) in (0, 1) and row.get(m2_key) is not None]
            if not eligible:
                continue
            comparable = [row for row in eligible if row.get(m1_key) is not None]
            if not comparable:
                continue
            m1 = [(int(row[outcome_key]), float(row[m1_key])) for row in comparable]
            m2 = [(int(row[outcome_key]), float(row[m2_key])) for row in comparable]
            m1_ll = _log_loss(m1); m2_ll = _log_loss(m2)
            folds.append({
                "season": season, "market": market, "n": len(comparable), "eligible_n": len(eligible),
                "m1_coverage": len(comparable) / len(eligible), "m1_log_loss": m1_ll, "m2_log_loss": m2_ll,
                "m1_brier": _brier(m1), "m2_brier": _brier(m2), "m2_beats_m1": m2_ll < m1_ll,
                "m2_probability_source": "PRODUCTION_M2_JOINT_RESIDUAL_PLUS_FOLD_SAFE_ISOTONIC",
            })
    return folds


def build_production_nfl_validation_evidence(
    rows: Iterable[dict[str, Any]], *, source_uri: str, source_sha256: str, source_manifest_sha256: str,
    min_train_seasons: int = 2, min_calibration_fit_seasons: int = 2,
    calibration_bins: int = 10, calibration_min_bin_n: int = 25, calibration_threshold: float = 0.05,
    fold_win_threshold: float = 0.65, ridge_alpha: float = 10.0,
) -> dict[str, Any]:
    """Return hash-bound per-fold production evidence for spread and total."""
    anchor_hash = _sha256(source_sha256, "NFL_PRODUCTION_SOURCE_SHA256_INVALID")
    manifest_hash = _sha256(source_manifest_sha256, "NFL_PRODUCTION_SOURCE_MANIFEST_SHA256_INVALID")
    raw = build_production_nfl_raw_evaluations(rows, min_train_seasons=min_train_seasons, ridge_alpha=ridge_alpha)
    calibrated = calibrate_nfl_evaluations(raw, min_fit_seasons=min_calibration_fit_seasons)
    folds = _folds_with_brier(calibrated)
    calibration = build_calibration_evidence(
        calibrated, bins=calibration_bins, min_bin_n=calibration_min_bin_n,
        max_bin_deviation_threshold=calibration_threshold,
    )
    validation_rows = [{
        "season": int(row["season"]), "market": str(row["market"]),
        "m1_log_loss": float(row["m1_log_loss"]), "m2_log_loss": float(row["m2_log_loss"]),
    } for row in folds]
    validated = validate_real_history_bundle(FootballValidationBundle(
        sport="nfl", provenance="real", source_uri=str(source_uri), source_sha256=anchor_hash, rows=validation_rows,
    ))
    promotion = build_promotion_evidence(validated)
    per_market: dict[str, dict[str, Any]] = {}
    for market, evidence in promotion.items():
        record = asdict(evidence)
        record["production_logic_pass"] = bool(evidence.fold_total > 0 and evidence.fold_win_rate >= float(fold_win_threshold))
        record["required_fold_win_rate"] = float(fold_win_threshold); record["calibration"] = calibration.get(market)
        per_market[market] = record

    return {
        "schema_version": 2, "model_id": PRODUCTION_NFL_M2_MODEL_ID, "feature_contract": NFL_M2_FEATURE_CONTRACT,
        "provenance": "REAL_PUBLIC_HISTORY", "source_uri": str(source_uri), "source_sha256": anchor_hash,
        "source_manifest_sha256": manifest_hash, "raw_evaluation_count": len(raw),
        "calibrated_evaluation_count": sum(
            row.get("m2_home_cover_calibrated_prob") is not None or row.get("m2_over_calibrated_prob") is not None
            for row in calibrated
        ),
        "fold_count": len(folds), "folds": folds, "calibration_evidence": calibration,
        "promotion_evidence": per_market,
        "parameters": {
            "min_train_seasons": int(min_train_seasons), "min_calibration_fit_seasons": int(min_calibration_fit_seasons),
            "calibration_bins": int(calibration_bins), "calibration_min_bin_n": int(calibration_min_bin_n),
            "calibration_threshold": float(calibration_threshold), "fold_win_threshold": float(fold_win_threshold),
            "ridge_alpha": float(ridge_alpha),
        },
        "evidence_note": (
            "Exact production model identity. M2 is fit only on prior-season market-blind features; paired training "
            "residuals generate the joint score distribution; closing lines enter only after that distribution exists; "
            "isotonic calibration is fit only on prior OOS seasons."
        ),
    }
