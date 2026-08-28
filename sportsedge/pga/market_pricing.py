from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Mapping

from sportsedge.truth_gate import american_to_decimal


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


@dataclass(frozen=True)
class DeadHeatMarketPrice:
    market: str
    selection: str
    offered_american: float
    raw_finish_probability: float
    expected_paid_fraction: float
    expected_value: float


def _prob(value: float, *, label: str, open_interval: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)):
        raise ValueError(f"PGA_{label.upper()}_INVALID")
    p = float(value)
    if open_interval:
        if not 0.0 < p < 1.0:
            raise ValueError(f"PGA_{label.upper()}_INVALID")
    elif not 0.0 <= p <= 1.0:
        raise ValueError(f"PGA_{label.upper()}_INVALID")
    return p


def american_to_implied(odds: float) -> float:
    return 1.0 / american_to_decimal(odds)


def probability_to_american(probability: float) -> float:
    p = _prob(probability, label="probability", open_interval=True)
    return -100.0 * p / (1.0 - p) if p >= 0.5 else 100.0 * (1.0 - p) / p


def two_way_no_vig(odds_a: float, odds_b: float) -> tuple[float, float]:
    pa = american_to_implied(odds_a)
    pb = american_to_implied(odds_b)
    total = pa + pb
    if not isfinite(total) or total <= 0:
        raise ValueError("PGA_TWO_WAY_MARKET_INVALID")
    return pa / total, pb / total


def full_field_no_vig(prices: Mapping[str, float], *, market_complete: bool) -> dict[str, float]:
    """Normalize an exhaustive mutually-exclusive field such as outright/FRL.

    A partial field must not be normalized to 100%; doing so manufactures fair
    probabilities by redistributing omitted players' mass.
    """
    if type(market_complete) is not bool:
        raise ValueError("PGA_MARKET_COMPLETE_MUST_BE_BOOL")
    if not market_complete:
        raise ValueError("PGA_COMPLETE_FIELD_REQUIRED_FOR_NWAY_DEVIG")
    if not isinstance(prices, Mapping) or len(prices) < 2:
        raise ValueError("PGA_FULL_FIELD_MARKET_INVALID")
    names = [str(name).strip() for name in prices]
    if any(not name for name in names) or len({name.casefold() for name in names}) != len(names):
        raise ValueError("PGA_FULL_FIELD_IDENTITY_INVALID")
    raw = {str(name): american_to_implied(odds) for name, odds in prices.items()}
    total = sum(raw.values())
    if not isfinite(total) or total <= 0:
        raise ValueError("PGA_FULL_FIELD_MARKET_INVALID")
    return {name: probability / total for name, probability in raw.items()}


def decimal_profit_per_unit(american_odds: float) -> float:
    return american_to_decimal(american_odds) - 1.0


def expected_value_per_unit(model_probability: float, american_odds: float) -> float:
    p = _prob(model_probability, label="model_probability")
    dec = american_to_decimal(american_odds)
    return p * dec - 1.0


def full_kelly_fraction(model_probability: float, american_odds: float) -> float:
    p = _prob(model_probability, label="model_probability")
    b = decimal_profit_per_unit(american_odds)
    q = 1.0 - p
    raw = (b * p - q) / b
    return min(1.0, max(0.0, raw))


def price_selection(
    *,
    market: str,
    selection: str,
    offered_american: float,
    model_probability: float,
    market_probability: float,
) -> MarketPrice:
    if not str(market).strip() or not str(selection).strip():
        raise ValueError("PGA_MARKET_IDENTITY_REQUIRED")
    mp = _prob(model_probability, label="model_probability")
    mkp = _prob(market_probability, label="market_probability", open_interval=True)
    american_to_decimal(offered_american)
    fair = probability_to_american(mp) if 0.0 < mp < 1.0 else float("-inf") if mp == 1.0 else float("inf")
    return MarketPrice(
        market=str(market),
        selection=str(selection),
        offered_american=float(offered_american),
        model_probability=mp,
        market_probability=mkp,
        fair_american=fair,
        edge=mp - mkp,
        expected_value=expected_value_per_unit(mp, offered_american),
        full_kelly=full_kelly_fraction(mp, offered_american),
    )


def price_dead_heat_position(
    *,
    market: str,
    selection: str,
    offered_american: float,
    raw_finish_probability: float,
    expected_paid_fraction: float,
) -> DeadHeatMarketPrice:
    """Price top-K/FRL-style dead-heat settlement from simulated payout share."""
    if not str(market).strip() or not str(selection).strip():
        raise ValueError("PGA_MARKET_IDENTITY_REQUIRED")
    raw = _prob(raw_finish_probability, label="raw_finish_probability")
    paid = _prob(expected_paid_fraction, label="expected_paid_fraction")
    if paid > raw + 1e-12:
        raise ValueError("PGA_DEAD_HEAT_PAID_FRACTION_EXCEEDS_HIT_PROBABILITY")
    dec = american_to_decimal(offered_american)
    return DeadHeatMarketPrice(
        market=str(market),
        selection=str(selection),
        offered_american=float(offered_american),
        raw_finish_probability=raw,
        expected_paid_fraction=paid,
        expected_value=paid * dec - 1.0,
    )
