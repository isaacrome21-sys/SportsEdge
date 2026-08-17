"""CFB M2 v1: market-blind football features and walk-forward comparison.

Feature contract: opponent-adjusted efficiency, returning production,
preseason prior rating, and venue HFA. Sportsbook lines/prices/probabilities
are explicitly prohibited from M2 features.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import log
from typing import Any, Iterable

from sportsedge.core.walkforward.season import season_walk_forward


BANNED_MARKET_KEYS = {
    "spread", "spread_line", "total", "total_line", "line", "price",
    "american_odds", "decimal_odds", "implied_probability", "implied_prob",
    "novig_prob", "no_vig_prob", "book", "sportsbook", "closing_line",
    "closing_price",
}


def _dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError("NAIVE_TIMESTAMP")
    return dt


def _assert_market_blind(value: Any, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in BANNED_MARKET_KEYS:
                raise ValueError(f"M2_MARKET_DATA_PROHIBITED:{path}.{key}")
            _assert_market_blind(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for i, child in enumerate(value):
            _assert_market_blind(child, f"{path}[{i}]")


def _num(row: dict[str, Any], key: str) -> float:
    if key not in row:
        raise ValueError(f"M2_FEATURE_MISSING:{key}")
    value = float(row[key])
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError(f"M2_FEATURE_NONFINITE:{key}")
    return value


def build_cfb_m2_features(source: dict[str, Any]) -> dict[str, float | str]:
    _assert_market_blind(source)
    asof = _dt(source.get("feature_asof_ts"))
    start = _dt(source.get("game_start_ts"))
    if not asof < start:
        raise ValueError("FEATURE_ASOF_NOT_BEFORE_GAME_START")

    off_epa = _num(source, "off_epa")
    def_epa = _num(source, "def_epa")
    opp_off = _num(source, "opp_off_epa")
    opp_def = _num(source, "opp_def_epa")
    returning = _num(source, "returning_production")
    prior = _num(source, "prior_rating")
    hfa = _num(source, "venue_hfa")

    return {
        "adj_off_eff": off_epa - opp_def,
        "adj_def_eff": def_epa - opp_off,
        "returning_production": returning,
        "prior_rating": prior,
        "venue_hfa": hfa,
        "feature_asof_ts": asof.isoformat(),
    }


@dataclass(frozen=True)
class FoldMarketComparison:
    market: str
    test_season: int
    train_seasons: tuple[int, ...]
    n: int
    m1_log_loss: float
    m2_log_loss: float
    m2_beats_m1: bool


def _log_loss(rows: Iterable[dict[str, Any]], prob_key: str) -> float:
    values = list(rows)
    if not values:
        raise ValueError("EMPTY_EVALUATION_FOLD")
    total = 0.0
    eps = 1e-12
    for row in values:
        y = int(row["outcome"])
        if y not in (0, 1):
            raise ValueError("OUTCOME_NOT_BINARY")
        p = min(1.0 - eps, max(eps, float(row[prob_key])))
        total += -(y * log(p) + (1 - y) * log(1.0 - p))
    return total / len(values)


def walkforward_m2_vs_m1(rows: Iterable[dict[str, Any]], min_train_seasons: int = 2) -> list[FoldMarketComparison]:
    data = list(rows)
    if not data:
        return []
    folds = season_walk_forward(data, season_key="season", min_train_seasons=min_train_seasons)
    out: list[FoldMarketComparison] = []
    for fold in folds:
        train_seasons = tuple(sorted({int(r["season"]) for r in fold.train_rows}))
        markets = sorted({str(r["market"]) for r in fold.test_rows})
        for market in markets:
            test_rows = [r for r in fold.test_rows if str(r["market"]) == market]
            m1 = _log_loss(test_rows, "m1_prob")
            m2 = _log_loss(test_rows, "m2_prob")
            out.append(FoldMarketComparison(
                market=market,
                test_season=int(fold.test_season),
                train_seasons=train_seasons,
                n=len(test_rows),
                m1_log_loss=m1,
                m2_log_loss=m2,
                m2_beats_m1=m2 < m1,
            ))
    return out
