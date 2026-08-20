"""NFL M2 v1: market-blind features with explicit starting-QB adjustment."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import log
from typing import Any, Iterable

from sportsedge.core.position_matchup import build_positional_matchup_features
from sportsedge.core.walkforward.season import season_walk_forward

BANNED_MARKET_KEYS = {
    "spread", "spread_line", "total", "total_line", "line", "price",
    "american_odds", "decimal_odds", "implied_probability", "implied_prob",
    "novig_prob", "no_vig_prob", "book", "sportsbook", "closing_line",
    "closing_price",
}

# Common aliases that can otherwise sneak sportsbook state into M2 while
# avoiding an exact-key grep. Keep this list targeted so legitimate football
# concepts such as offensive_line_continuity and total_yards_prior remain valid.
BANNED_MARKET_ALIASES = {
    "home_spread", "away_spread", "consensus_spread", "market_spread", "closing_spread",
    "market_total", "consensus_total", "closing_total", "sportsbook_total", "game_total",
    "market_implied_probability", "market_implied_prob", "consensus_implied_probability",
    "consensus_implied_prob", "sportsbook_price", "book_price", "closing_odds",
    "opening_odds", "market_odds", "consensus_odds", "sportsbook_odds",
    "opening_spread", "opening_total", "book_spread", "book_total",
}


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
        for i, child in enumerate(value):
            _assert_market_blind(child, f"{path}[{i}]")


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
    if value != value or value in (float("inf"), float("-inf")):
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
        y = int(row["outcome"])
        if y not in (0, 1):
            raise ValueError("OUTCOME_NOT_BINARY")
        p = min(1.0 - eps, max(eps, float(row[key])))
        total += -(y * log(p) + (1 - y) * log(1.0 - p))
    return total / len(values)


def walkforward_nfl_m2_vs_m1(rows: Iterable[dict[str, Any]], min_train_seasons: int = 2) -> list[NFLFoldMarketComparison]:
    data = list(rows)
    if not data:
        return []
    folds = season_walk_forward(data, season_key="season", min_train_seasons=min_train_seasons)
    out: list[NFLFoldMarketComparison] = []
    for fold in folds:
        train_seasons = tuple(sorted({int(r["season"]) for r in fold.train_rows}))
        for market in sorted({str(r["market"]) for r in fold.test_rows}):
            test_rows = [r for r in fold.test_rows if str(r["market"]) == market]
            m1 = _log_loss(test_rows, "m1_prob")
            m2 = _log_loss(test_rows, "m2_prob")
            out.append(NFLFoldMarketComparison(market, int(fold.test_season), train_seasons, len(test_rows), m1, m2, m2 < m1))
    return out
