from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Mapping


@dataclass(frozen=True)
class MarketPrice:
    market: str
    selection: str
    offered_american: float
    model_probability: float
    market_probability: float
    fair_american: float
    edge: float
    expected_value: float
    full_kelly: float


def american_to_implied(odds: float) -> float:
    """Convert American odds to raw implied probability."""
    if not isfinite(odds) or odds == 0:
        raise ValueError("American odds must be finite and non-zero")
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return (-odds) / ((-odds) + 100.0)


def probability_to_american(probability: float) -> float:
    """Convert probability to fair American odds."""
    p = float(probability)
    if not 0.0 < p < 1.0:
        raise ValueError("probability must be strictly between 0 and 1")
    if p >= 0.5:
        return -100.0 * p / (1.0 - p)
    return 100.0 * (1.0 - p) / p


def two_way_no_vig(odds_a: float, odds_b: float) -> tuple[float, float]:
    """Proportional no-vig probabilities for a two-way market."""
    pa = american_to_implied(odds_a)
    pb = american_to_implied(odds_b)
    total = pa + pb
    if total <= 0:
        raise ValueError("invalid two-way market")
    return pa / total, pb / total


def full_field_no_vig(prices: Mapping[str, float]) -> dict[str, float]:
    """Normalize a mutually-exclusive field such as an outright winner market."""
    if not prices:
        return {}
    raw = {name: american_to_implied(odds) for name, odds in prices.items()}
    total = sum(raw.values())
    if total <= 0:
        raise ValueError("invalid full-field market")
    return {name: p / total for name, p in raw.items()}


def decimal_profit_per_unit(american_odds: float) -> float:
    if american_odds > 0:
        return american_odds / 100.0
    return 100.0 / abs(american_odds)


def expected_value_per_unit(model_probability: float, american_odds: float) -> float:
    """Expected net profit per 1 unit staked."""
    p = float(model_probability)
    if not 0.0 <= p <= 1.0:
        raise ValueError("model_probability must be in [0, 1]")
    b = decimal_profit_per_unit(american_odds)
    return p * b - (1.0 - p)


def full_kelly_fraction(model_probability: float, american_odds: float) -> float:
    """Uncapped full Kelly fraction; negative values are returned as zero."""
    p = float(model_probability)
    if not 0.0 <= p <= 1.0:
        raise ValueError("model_probability must be in [0, 1]")
    b = decimal_profit_per_unit(american_odds)
    if b <= 0:
        raise ValueError("odds must imply positive profit on a win")
    q = 1.0 - p
    return max(0.0, (b * p - q) / b)


def price_selection(
    *,
    market: str,
    selection: str,
    offered_american: float,
    model_probability: float,
    market_probability: float,
) -> MarketPrice:
    mp = float(model_probability)
    mkp = float(market_probability)
    if not 0.0 <= mp <= 1.0 or not 0.0 <= mkp <= 1.0:
        raise ValueError("probabilities must be in [0, 1]")
    if mp in (0.0, 1.0):
        # Avoid infinite fair-odds rendering. Extreme model probabilities should
        # be handled upstream by calibration rather than emitted as infinities.
        fair = float("-inf") if mp == 1.0 else float("inf")
    else:
        fair = probability_to_american(mp)
    return MarketPrice(
        market=market,
        selection=selection,
        offered_american=float(offered_american),
        model_probability=mp,
        market_probability=mkp,
        fair_american=fair,
        edge=mp - mkp,
        expected_value=expected_value_per_unit(mp, offered_american),
        full_kelly=full_kelly_fraction(mp, offered_american),
    )
