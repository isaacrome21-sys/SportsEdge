"""NFL M2 v1: market-blind features and season-ordered production fitting.

The production M2 path is deliberately separated from sportsbook evaluation.
Feature construction rejects market-derived inputs, score-model fitting consumes
only validated feature dictionaries plus realized scores, and market lines are
applied only after a joint score distribution exists.

The fitted distribution is nonparametric: paired margin/total residuals from the
training fold are replayed together around the held-out game's market-blind
predicted means. That preserves train-observed joint shape without injecting
historical sportsbook lines or hard-coding key-number probability mass.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite, log, sqrt
from typing import Any, Iterable

import numpy as np

from sportsedge.core.position_matchup import build_positional_matchup_features
from sportsedge.core.walkforward.season import season_walk_forward

NFL_M2_FEATURE_CONTRACT = "NFL_M2_V1_MARKET_BLIND"
PRODUCTION_NFL_M2_MODEL_ID = "nfl_m2_ridge_v1"

BANNED_MARKET_KEYS = {
    "spread", "spread_line", "total", "total_line", "line", "price",
    "american_odds", "decimal_odds", "implied_probability", "implied_prob",
    "novig_prob", "no_vig_prob", "book", "sportsbook", "closing_line",
    "closing_price",
}
BANNED_MARKET_ALIASES = {
    "home_spread", "away_spread", "consensus_spread", "market_spread", "closing_spread",
    "market_total", "consensus_total", "closing_total", "sportsbook_total", "game_total",
    "market_implied_probability", "market_implied_prob", "consensus_implied_probability",
    "consensus_implied_prob", "sportsbook_price", "book_price", "closing_odds",
    "opening_odds", "market_odds", "consensus_odds", "sportsbook_odds",
    "opening_spread", "opening_total", "book_spread", "book_total",
}

_REQUIRED_MODEL_FEATURES = (
    "adj_off_epa", "adj_def_epa", "pass_epa", "rush_epa", "pressure_for",
    "pressure_allowed", "success_rate", "explosive_rate", "rest_diff_days",
    "travel_miles", "timezone_crossings", "short_week", "bye_week", "wind_mph",
    "roof_closed", "qb_adjustment", "prior_efficiency", "prior_weight",
)
_OPTIONAL_MODEL_FEATURES = (
    "opp_wr_target_share_oe_allowed", "opp_te_target_share_oe_allowed",
    "opp_rb_target_share_oe_allowed", "opp_wr_target_share_oe_weighted",
    "opp_te_target_share_oe_weighted", "opp_rb_target_share_oe_weighted",
    "defensive_playcaller_continuity_weight", "defensive_playcaller_changed",
    "off_wr_target_share", "off_te_target_share", "off_rb_target_share",
    "wr_usage_x_opp_target_oe", "te_usage_x_opp_target_oe", "rb_usage_x_opp_target_oe",
    "positional_target_matchup_pressure",
)
_MODEL_FEATURES = _REQUIRED_MODEL_FEATURES + _OPTIONAL_MODEL_FEATURES


def _is_market_derived_key(key: Any) -> bool:
    name = str(key).strip().lower()
    if name in BANNED_MARKET_KEYS or name in BANNED_MARKET_ALIASES:
        return True
    if "implied_prob" in name or "implied_probability" in name:
        return True
    if "novig_prob" in name or "no_vig_prob" in name or "no_vig_probability" in name:
        return True
    return False


def _assert_market_blind(value: Any, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if _is_market_derived_key(key):
                raise ValueError(f"M2_MARKET_DATA_PROHIBITED:{path}.{key}")
            _assert_market_blind(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _assert_market_blind(child, f"{path}[{index}]")


def _dt(value: Any) -> datetime:
    text = str(value).replace("Z", "+00:00")
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError("NAIVE_TIMESTAMP")
    return dt


def _num(row: dict[str, Any], key: str) -> float:
    if key not in row:
        raise ValueError(f"M2_FEATURE_MISSING:{key}")
    value = float(row[key])
    if not isfinite(value):
        raise ValueError(f"M2_FEATURE_NONFINITE:{key}")
    return value


def build_nfl_m2_features(source: dict[str, Any]) -> dict[str, float | str]:
    _assert_market_blind(source)
    asof = _dt(source.get("feature_asof_ts"))
    start = _dt(source.get("game_start_ts"))
    if not asof < start:
        raise ValueError("FEATURE_ASOF_NOT_BEFORE_GAME_START")
    qb_id = str(source.get("qb_id", "")).strip()
    if not qb_id:
        raise ValueError("M2_QB_ID_MISSING")

    off = _num(source, "off_epa")
    deff = _num(source, "def_epa")
    opp_off = _num(source, "opp_off_epa")
    opp_def = _num(source, "opp_def_epa")
    prior_weight = _num(source, "prior_weight")
    if not 0.0 <= prior_weight <= 1.0:
        raise ValueError("M2_PRIOR_WEIGHT_OUT_OF_RANGE")

    features: dict[str, float | str] = {
        "feature_contract": NFL_M2_FEATURE_CONTRACT,
        "adj_off_epa": off - opp_def,
        "adj_def_epa": deff - opp_off,
        "pass_epa": _num(source, "pass_epa"),
        "rush_epa": _num(source, "rush_epa"),
        "pressure_for": _num(source, "pressure_for"),
        "pressure_allowed": _num(source, "pressure_allowed"),
        "success_rate": _num(source, "success_rate"),
        "explosive_rate": _num(source, "explosive_rate"),
        "rest_diff_days": _num(source, "rest_diff_days"),
        "travel_miles": _num(source, "travel_miles"),
        "timezone_crossings": _num(source, "timezone_crossings"),
        "short_week": _num(source, "short_week"),
        "bye_week": _num(source, "bye_week"),
        "wind_mph": _num(source, "wind_mph"),
        "roof_closed": _num(source, "roof_closed"),
        "qb_id": qb_id,
        "qb_adjustment": _num(source, "qb_adjustment"),
        "prior_efficiency": _num(source, "prior_efficiency"),
        "prior_weight": prior_weight,
        "feature_asof_ts": asof.isoformat(),
    }
    features.update(build_positional_matchup_features(source))
    return features


def _validated_feature_vector(features: dict[str, Any], side: str) -> list[float]:
    _assert_market_blind(features, path=f"{side}_features")
    if features.get("feature_contract") != NFL_M2_FEATURE_CONTRACT:
        raise ValueError("NFL_M2_FEATURE_CONTRACT_REQUIRED")
    if not str(features.get("qb_id", "")).strip():
        raise ValueError("NFL_M2_QB_ID_REQUIRED")
    if not str(features.get("feature_asof_ts", "")).strip():
        raise ValueError("NFL_M2_FEATURE_ASOF_REQUIRED")

    values: list[float] = []
    for key in _REQUIRED_MODEL_FEATURES:
        if key not in features:
            raise ValueError(f"NFL_M2_MODEL_FEATURE_MISSING:{key}")
        value = float(features[key])
        if not isfinite(value):
            raise ValueError(f"NFL_M2_MODEL_FEATURE_NONFINITE:{key}")
        values.append(value)
    for key in _OPTIONAL_MODEL_FEATURES:
        value = float(features.get(key, 0.0))
        if not isfinite(value):
            raise ValueError(f"NFL_M2_MODEL_FEATURE_NONFINITE:{key}")
        values.append(value)
    return values


def _game_feature_vector(row: dict[str, Any]) -> list[float]:
    home = row.get("home_features")
    away = row.get("away_features")
    if not isinstance(home, dict) or not isinstance(away, dict):
        raise ValueError("NFL_M2_GAME_FEATURES_REQUIRED")
    return _validated_feature_vector(home, "home") + _validated_feature_vector(away, "away")


def _target_scores(row: dict[str, Any]) -> tuple[float, float]:
    try:
        home = float(row["home_score"])
        away = float(row["away_score"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("NFL_M2_REALIZED_SCORE_REQUIRED") from exc
    if not isfinite(home) or not isfinite(away):
        raise ValueError("NFL_M2_REALIZED_SCORE_NONFINITE")
    return home - away, home + away


@dataclass(frozen=True)
class NFLM2ScoreModel:
    model_id: str
    feature_contract: str
    feature_names: tuple[str, ...]
    feature_means: tuple[float, ...]
    feature_scales: tuple[float, ...]
    margin_coefficients: tuple[float, ...]
    total_coefficients: tuple[float, ...]
    train_seasons: tuple[int, ...]
    ridge_alpha: float
    margin_sigma: float
    total_sigma: float
    residual_correlation: float
    residual_pairs: tuple[tuple[float, float], ...]

    def predict(self, row: dict[str, Any]) -> tuple[float, float]:
        raw = np.asarray(_game_feature_vector(row), dtype=float)
        means = np.asarray(self.feature_means, dtype=float)
        scales = np.asarray(self.feature_scales, dtype=float)
        if raw.shape != means.shape or raw.shape != scales.shape:
            raise ValueError("NFL_M2_MODEL_FEATURE_DIMENSION_MISMATCH")
        design = np.concatenate(([1.0], (raw - means) / scales))
        margin = float(design @ np.asarray(self.margin_coefficients, dtype=float))
        total = float(design @ np.asarray(self.total_coefficients, dtype=float))
        if not isfinite(margin) or not isfinite(total):
            raise ValueError("NFL_M2_MODEL_PREDICTION_NONFINITE")
        return margin, total


def _ridge_coefficients(design: np.ndarray, target: np.ndarray, ridge_alpha: float) -> np.ndarray:
    penalty = np.eye(design.shape[1], dtype=float) * float(ridge_alpha)
    penalty[0, 0] = 0.0
    lhs = design.T @ design + penalty
    rhs = design.T @ target
    try:
        return np.linalg.solve(lhs, rhs)
    except np.linalg.LinAlgError:
        return np.linalg.pinv(lhs) @ rhs


def fit_nfl_m2_score_model(
    rows: Iterable[dict[str, Any]],
    *,
    ridge_alpha: float = 10.0,
) -> NFLM2ScoreModel:
    """Fit margin/total ridge means plus paired train residual distribution."""
    data = [dict(row) for row in rows]
    if len(data) < 2:
        raise ValueError("NFL_M2_TRAINING_ROWS_INSUFFICIENT")
    alpha = float(ridge_alpha)
    if not isfinite(alpha) or alpha < 0.0:
        raise ValueError("NFL_M2_RIDGE_ALPHA_INVALID")

    raw_x = np.asarray([_game_feature_vector(row) for row in data], dtype=float)
    if raw_x.ndim != 2 or raw_x.shape[0] != len(data):
        raise ValueError("NFL_M2_TRAINING_MATRIX_INVALID")
    means = raw_x.mean(axis=0)
    scales = raw_x.std(axis=0)
    scales = np.where(scales > 1e-12, scales, 1.0)
    design = np.column_stack((np.ones(len(data), dtype=float), (raw_x - means) / scales))

    targets = [_target_scores(row) for row in data]
    margin_y = np.asarray([target[0] for target in targets], dtype=float)
    total_y = np.asarray([target[1] for target in targets], dtype=float)
    margin_coef = _ridge_coefficients(design, margin_y, alpha)
    total_coef = _ridge_coefficients(design, total_y, alpha)

    margin_residual = margin_y - design @ margin_coef
    total_residual = total_y - design @ total_coef
    margin_sigma = float(sqrt(float(np.mean(margin_residual ** 2))))
    total_sigma = float(sqrt(float(np.mean(total_residual ** 2))))
    if margin_sigma <= 1e-12 or total_sigma <= 1e-12:
        raise ValueError("NFL_M2_RESIDUAL_SIGMA_ZERO")
    covariance = float(np.mean((margin_residual - margin_residual.mean()) * (total_residual - total_residual.mean())))
    corr = covariance / (float(np.std(margin_residual)) * float(np.std(total_residual)))
    if not isfinite(corr):
        corr = 0.0
    corr = max(-1.0, min(1.0, corr))

    train_seasons = tuple(sorted({int(row["season"]) for row in data}))
    if not train_seasons:
        raise ValueError("NFL_M2_TRAINING_SEASONS_REQUIRED")
    feature_names = tuple(
        [f"home_{name}" for name in _MODEL_FEATURES]
        + [f"away_{name}" for name in _MODEL_FEATURES]
    )
    residual_pairs = tuple(
        (float(margin), float(total))
        for margin, total in zip(margin_residual.tolist(), total_residual.tolist())
    )
    return NFLM2ScoreModel(
        model_id=PRODUCTION_NFL_M2_MODEL_ID,
        feature_contract=NFL_M2_FEATURE_CONTRACT,
        feature_names=feature_names,
        feature_means=tuple(float(value) for value in means.tolist()),
        feature_scales=tuple(float(value) for value in scales.tolist()),
        margin_coefficients=tuple(float(value) for value in margin_coef.tolist()),
        total_coefficients=tuple(float(value) for value in total_coef.tolist()),
        train_seasons=train_seasons,
        ridge_alpha=alpha,
        margin_sigma=margin_sigma,
        total_sigma=total_sigma,
        residual_correlation=corr,
        residual_pairs=residual_pairs,
    )


def _reconcile_scores(raw_margin: float, raw_total: float) -> dict[str, int]:
    margin = int(round(float(raw_margin)))
    total = max(abs(margin), max(0, int(round(float(raw_total)))))
    if (total - margin) % 2 != 0:
        total += 1
    home = (total + margin) // 2
    away = (total - margin) // 2
    if home < 0 or away < 0:
        raise ValueError("NFL_M2_SCORE_RECONCILIATION_NEGATIVE")
    return {"home_score": home, "away_score": away, "margin": home - away, "total": home + away}


def derive_nfl_m2_score_distribution(
    model: NFLM2ScoreModel,
    row: dict[str, Any],
) -> tuple[dict[str, int], ...]:
    """Replay paired train residuals around a held-out predicted margin/total."""
    if model.model_id != PRODUCTION_NFL_M2_MODEL_ID or model.feature_contract != NFL_M2_FEATURE_CONTRACT:
        raise ValueError("NFL_M2_MODEL_IDENTITY_INVALID")
    if not model.residual_pairs:
        raise ValueError("NFL_M2_RESIDUAL_DISTRIBUTION_MISSING")
    margin_mu, total_mu = model.predict(dict(row))
    return tuple(
        _reconcile_scores(margin_mu + margin_residual, total_mu + total_residual)
        for margin_residual, total_residual in model.residual_pairs
    )


def price_nfl_m2_game_markets(
    distribution: Iterable[dict[str, int]],
    *,
    spread_line: float,
    total_line: float,
) -> dict[str, dict[str, float]]:
    """Apply sportsbook thresholds only after the model distribution exists.

    ``spread_line`` is the home-team handicap, consistent with the shared
    football market contract. A home cover therefore occurs when
    ``margin + spread_line > 0``; at a zero spread, cover probability equals
    home moneyline win probability.
    """
    rows = [dict(row) for row in distribution]
    if not rows:
        raise ValueError("NFL_M2_SCORE_DISTRIBUTION_EMPTY")
    spread = float(spread_line)
    total = float(total_line)
    if not isfinite(spread) or not isfinite(total):
        raise ValueError("NFL_M2_MARKET_LINE_NONFINITE")
    n = float(len(rows))
    adjusted_margins = [float(row["margin"]) + spread for row in rows]
    return {
        "moneyline": {
            "home": sum(int(row["margin"]) > 0 for row in rows) / n,
            "away": sum(int(row["margin"]) < 0 for row in rows) / n,
            "tie": sum(int(row["margin"]) == 0 for row in rows) / n,
        },
        "spread": {
            "home": sum(value > 0 for value in adjusted_margins) / n,
            "away": sum(value < 0 for value in adjusted_margins) / n,
            "push": sum(value == 0 for value in adjusted_margins) / n,
        },
        "total": {
            "over": sum(float(row["total"]) > total for row in rows) / n,
            "under": sum(float(row["total"]) < total for row in rows) / n,
            "push": sum(float(row["total"]) == total for row in rows) / n,
        },
    }


def walkforward_fit_nfl_m2_score_model(
    rows: Iterable[dict[str, Any]],
    *,
    min_train_seasons: int = 2,
    ridge_alpha: float = 10.0,
) -> list[dict[str, Any]]:
    """Fit on earlier seasons only and predict every held-out season."""
    data = [dict(row) for row in rows]
    if not data:
        return []
    folds = season_walk_forward(data, season_key="season", min_train_seasons=min_train_seasons)
    out: list[dict[str, Any]] = []
    for fold in folds:
        model = fit_nfl_m2_score_model(fold.train_rows, ridge_alpha=ridge_alpha)
        if int(fold.test_season) in model.train_seasons:
            raise ValueError("NFL_M2_TEST_SEASON_IN_TRAINING")
        for raw in fold.test_rows:
            row = dict(raw)
            margin, total = model.predict(row)
            out.append({
                "game_id": str(row.get("game_id") or ""),
                "season": int(row["season"]),
                "week": row.get("week"),
                "model_id": model.model_id,
                "feature_contract": model.feature_contract,
                "train_seasons": model.train_seasons,
                "ridge_alpha": model.ridge_alpha,
                "model_margin_mu": margin,
                "model_total_mu": total,
                "margin_sigma": model.margin_sigma,
                "total_sigma": model.total_sigma,
                "residual_correlation": model.residual_correlation,
            })
    return out


@dataclass(frozen=True)
class NFLFoldMarketComparison:
    market: str
    test_season: int
    train_seasons: tuple[int, ...]
    n: int
    m1_log_loss: float
    m2_log_loss: float
    m2_beats_m1: bool


def _log_loss(rows: Iterable[dict[str, Any]], key: str) -> float:
    values = list(rows)
    if not values:
        raise ValueError("EMPTY_EVALUATION_FOLD")
    eps = 1e-12
    total = 0.0
    for row in values:
        outcome = int(row["outcome"])
        if outcome not in (0, 1):
            raise ValueError("OUTCOME_NOT_BINARY")
        probability = min(1.0 - eps, max(eps, float(row[key])))
        total += -(outcome * log(probability) + (1 - outcome) * log(1.0 - probability))
    return total / len(values)


def walkforward_nfl_m2_vs_m1(
    rows: Iterable[dict[str, Any]],
    min_train_seasons: int = 2,
) -> list[NFLFoldMarketComparison]:
    """Legacy evaluator for already-produced probabilities; retained for compatibility."""
    data = list(rows)
    if not data:
        return []
    folds = season_walk_forward(data, season_key="season", min_train_seasons=min_train_seasons)
    out: list[NFLFoldMarketComparison] = []
    for fold in folds:
        train_seasons = tuple(sorted({int(row["season"]) for row in fold.train_rows}))
        for market in sorted({str(row["market"]) for row in fold.test_rows}):
            test_rows = [row for row in fold.test_rows if str(row["market"]) == market]
            m1 = _log_loss(test_rows, "m1_prob")
            m2 = _log_loss(test_rows, "m2_prob")
            out.append(NFLFoldMarketComparison(
                market, int(fold.test_season), train_seasons, len(test_rows), m1, m2, m2 < m1
            ))
    return out
