"""Development-only market-anchored CFB spread challenger.

The completed SDV score model supplies a raw home margin.  A paired sportsbook
spread supplies the market home margin.  This module fits only the small residual
correction frozen in issue #1602 and never changes the underlying score model.

Historical rows are already-touched development evidence.  These helpers create
no promotion, staking, or OFFICIAL authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping

VERSION = "CFB_MARKET_ANCHORED_SPREAD_V1"
FORWARD_MIN_ABS_ADJUSTMENT = 0.5


class CFBMarketAnchoredSpreadError(ValueError):
    pass


@dataclass(frozen=True)
class MarketAnchoredSpreadFit:
    intercept: float
    weight: float
    n: int
    season_start: int
    season_end: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "CFB_MARKET_ANCHORED_SPREAD_FIT_V1",
            "version": VERSION,
            "intercept": float(self.intercept),
            "weight": float(self.weight),
            "n": int(self.n),
            "season_start": int(self.season_start),
            "season_end": int(self.season_end),
            "forward_min_abs_adjustment_points": FORWARD_MIN_ABS_ADJUSTMENT,
            "evidence_role": "DEVELOPMENT_ONLY_ALREADY_TOUCHED",
            "authority": {
                "model_p": False,
                "promotion": False,
                "staking": False,
                "official": False,
            },
        }


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise CFBMarketAnchoredSpreadError(field + ":NUMERIC_REQUIRED")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise CFBMarketAnchoredSpreadError(field + ":NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise CFBMarketAnchoredSpreadError(field + ":FINITE_REQUIRED")
    return out


def _ols(xs: list[float], ys: list[float]) -> tuple[float, float]:
    if len(xs) != len(ys) or len(xs) < 2:
        raise CFBMarketAnchoredSpreadError("CFB_ANCHORED_SPREAD_FIT_ROWS_INSUFFICIENT")
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        raise CFBMarketAnchoredSpreadError("CFB_ANCHORED_SPREAD_SIGNAL_VARIANCE_ZERO")
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    weight = sxy / sxx
    intercept = my - weight * mx
    return intercept, weight


def fit_market_anchored_spread(
    predictions: Mapping[str, Mapping[str, Any]],
    lines: Mapping[str, Mapping[str, Any]],
) -> MarketAnchoredSpreadFit:
    xs: list[float] = []
    ys: list[float] = []
    seasons: list[int] = []
    for game_id, raw in predictions.items():
        market = lines.get(str(game_id))
        if not isinstance(market, Mapping) or market.get("spread") is None:
            continue
        try:
            season = int(raw["season"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CFBMarketAnchoredSpreadError("CFB_ANCHORED_SPREAD_SEASON_INVALID") from exc
        model_margin = _finite(raw.get("home_pred"), "home_pred") - _finite(raw.get("away_pred"), "away_pred")
        actual_margin = _finite(raw.get("home_pts"), "home_pts") - _finite(raw.get("away_pts"), "away_pts")
        # CFBD spread is the home handicap; market expected home margin is -spread.
        market_margin = -_finite(market.get("spread"), "spread")
        xs.append(model_margin - market_margin)
        ys.append(actual_margin - market_margin)
        seasons.append(season)
    if len(xs) < 1000:
        raise CFBMarketAnchoredSpreadError(
            f"CFB_ANCHORED_SPREAD_JOINED_ROWS_INSUFFICIENT:{len(xs)}"
        )
    intercept, weight = _ols(xs, ys)
    return MarketAnchoredSpreadFit(
        intercept=intercept,
        weight=weight,
        n=len(xs),
        season_start=min(seasons),
        season_end=max(seasons),
    )


def adjusted_home_margin(
    *,
    raw_model_home_margin: float,
    market_home_margin: float,
    intercept: float,
    weight: float,
) -> float:
    raw = _finite(raw_model_home_margin, "raw_model_home_margin")
    market = _finite(market_home_margin, "market_home_margin")
    b = _finite(intercept, "intercept")
    w = _finite(weight, "weight")
    return market + b + w * (raw - market)


def forward_track_eligible(*, adjusted_margin: float, market_home_margin: float) -> bool:
    delta = abs(_finite(adjusted_margin, "adjusted_margin") - _finite(market_home_margin, "market_home_margin"))
    return delta >= FORWARD_MIN_ABS_ADJUSTMENT


__all__ = [
    "CFBMarketAnchoredSpreadError",
    "FORWARD_MIN_ABS_ADJUSTMENT",
    "MarketAnchoredSpreadFit",
    "VERSION",
    "adjusted_home_margin",
    "fit_market_anchored_spread",
    "forward_track_eligible",
]
