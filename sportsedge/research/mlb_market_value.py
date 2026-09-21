"""Research-only MLB market-value helpers.

This module keeps price handling separate from predictive challengers. It does not
create Model_P, Truth Gate passage, staking authority, or OFFICIAL selections.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite

QUOTE_TTL = timedelta(seconds=180)
MAX_FUTURE_SKEW = timedelta(seconds=30)


class MarketValueError(ValueError):
    pass


def _aware(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise MarketValueError(f"AWARE_TIMESTAMP_REQUIRED:{name}")
    return value


def american_to_implied(price: int) -> float:
    if type(price) is not int or price == 0 or -100 < price < 100:
        raise MarketValueError("INVALID_AMERICAN_PRICE")
    return 100.0 / (price + 100.0) if price > 0 else (-price) / ((-price) + 100.0)


def implied_to_american(probability: float) -> int:
    p = float(probability)
    if not isfinite(p) or not 0.0 < p < 1.0:
        raise MarketValueError("INVALID_PROBABILITY")
    return round(100.0 * (1.0 - p) / p) if p < 0.5 else round(-100.0 * p / (1.0 - p))


def raw_expected_value(estimate_p: float, price: int) -> float:
    p = float(estimate_p)
    if not isfinite(p) or not 0.0 <= p <= 1.0:
        raise MarketValueError("INVALID_ESTIMATE_P")
    win_profit = price / 100.0 if price > 0 else 100.0 / (-price)
    return p * win_profit - (1.0 - p)


@dataclass(frozen=True)
class FreshQuote:
    selection: str
    american_price: int
    retrieved_at: datetime
    book: str = "DraftKings"

    def __post_init__(self) -> None:
        if not self.selection:
            raise MarketValueError("SELECTION_REQUIRED")
        american_to_implied(self.american_price)
        _aware(self.retrieved_at, "retrieved_at")
        if self.book != "DraftKings":
            raise MarketValueError("DRAFTKINGS_ONLY")


def validate_quote_freshness(quote: FreshQuote, *, now: datetime, event_start: datetime) -> None:
    now = _aware(now, "now")
    event_start = _aware(event_start, "event_start")
    if now >= event_start:
        raise MarketValueError("EVENT_ALREADY_STARTED")
    if quote.retrieved_at >= event_start:
        raise MarketValueError("POST_START_QUOTE_REFUSED")
    age = now - quote.retrieved_at
    if age > QUOTE_TTL:
        raise MarketValueError("STALE_QUOTE")
    if age < -MAX_FUTURE_SKEW:
        raise MarketValueError("QUOTE_FROM_FUTURE")


def _power_exponent(q1: float, q2: float) -> float:
    """Solve q1**k + q2**k = 1 for a two-way market by bisection."""
    if not (0.0 < q1 < 1.0 and 0.0 < q2 < 1.0) or q1 + q2 <= 1.0:
        raise MarketValueError("PAIR_DOES_NOT_CONTAIN_POSITIVE_VIG")
    lo, hi = 1.0, 16.0
    while q1**hi + q2**hi > 1.0:
        hi *= 2.0
        if hi > 1024:
            raise MarketValueError("POWER_DEVIG_DID_NOT_CONVERGE")
    for _ in range(100):
        mid = (lo + hi) / 2.0
        if q1**mid + q2**mid > 1.0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def paired_power_v1(
    first: FreshQuote,
    second: FreshQuote,
    *,
    now: datetime,
    event_start: datetime,
) -> dict[str, object]:
    """Two-way POWER_V1 research implementation with longshot sensitivity gate.

    The method is only valid for an exhaustive paired two-way market. A one-sided
    quote must not call this function.
    """
    if first.selection == second.selection:
        raise MarketValueError("DISTINCT_SELECTIONS_REQUIRED")
    validate_quote_freshness(first, now=now, event_start=event_start)
    validate_quote_freshness(second, now=now, event_start=event_start)
    if abs((first.retrieved_at - second.retrieved_at).total_seconds()) > 30:
        raise MarketValueError("PAIR_TIMESTAMP_SKEW")
    q1, q2 = american_to_implied(first.american_price), american_to_implied(second.american_price)
    k = _power_exponent(q1, q2)
    p1, p2 = q1**k, q2**k
    total = q1 + q2
    prop1, prop2 = q1 / total, q2 / total
    sensitivity_pp = max(abs(p1 - prop1), abs(p2 - prop2)) * 100.0
    longshot = first.american_price > 400 or second.american_price > 400
    if longshot and sensitivity_pp > 1.0:
        raise MarketValueError("LONGSHOT_DEVIG_SENSITIVITY_GT_1PP")
    return {
        "method": "POWER_V1",
        "fair_probabilities": {first.selection: p1, second.selection: p2},
        "fair_american": {first.selection: implied_to_american(p1), second.selection: implied_to_american(p2)},
        "sensitivity_pp_vs_proportional": sensitivity_pp,
        "longshot_sensitivity_pass": (not longshot) or sensitivity_pp <= 1.0,
        "authority": "RESEARCH_ONLY_NOT_MODEL_P_NOT_TRUTH_GATE_NOT_OFFICIAL",
    }


def one_sided_hr_value(
    *,
    estimate_p: float,
    quote: FreshQuote,
    now: datetime,
    event_start: datetime,
) -> dict[str, object]:
    """Raw one-sided HR comparison. Never labels a one-sided price no-vig/fair market."""
    validate_quote_freshness(quote, now=now, event_start=event_start)
    raw_implied = american_to_implied(quote.american_price)
    longshot = quote.american_price > 400
    return {
        "estimate_p": float(estimate_p),
        "raw_implied_probability": raw_implied,
        "raw_probability_gap": float(estimate_p) - raw_implied,
        "raw_ev_per_unit": raw_expected_value(float(estimate_p), quote.american_price),
        "no_vig_probability": None,
        "devig_method": None,
        "longshot_sensitivity_certified": False if longshot else None,
        "certification_blocker": "PAIRED_YES_NO_REQUIRED_FOR_DEVIG_SENSITIVITY" if longshot else "PAIRED_YES_NO_REQUIRED_FOR_DEVIG",
        "authority": "RESEARCH_ONLY_NOT_MODEL_P_NOT_TRUTH_GATE_NOT_OFFICIAL",
    }
