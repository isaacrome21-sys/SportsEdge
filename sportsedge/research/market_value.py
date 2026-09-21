"""Shared research economics for any win/loss/push market.

Probability readouts remain upstream. No no-vig pair is invented from a
one-sided quote; no ranking, context score, or EV grants betting authority.
"""
from datetime import datetime
from math import isfinite


def compare_price(*, win: float, push: float, american_odds: float | None,
                  quote_at: datetime | None, now: datetime, start: datetime,
                  ttl_seconds: float) -> dict:
    for value in (win, push, ttl_seconds):
        if isinstance(value, bool) or not isfinite(value):
            raise ValueError("NONFINITE_MARKET_INPUT")
    if not 0 <= win <= 1 or not 0 <= push <= 1 or win + push > 1:
        raise ValueError("INVALID_PROBABILITY_MASS")
    if ttl_seconds <= 0:
        raise ValueError("POSITIVE_QUOTE_TTL_REQUIRED")
    for timestamp in (now, start, quote_at):
        if timestamp is not None and (timestamp.tzinfo is None or timestamp.utcoffset() is None):
            raise ValueError("AWARE_TIMESTAMP_REQUIRED")
    loss = 1 - win - push
    conditional = win / (1 - push) if push < 1 else None
    fair = None
    if conditional is not None and 0 < conditional < 1:
        fair = (-100 * conditional / (1 - conditional) if conditional >= .5
                else 100 * (1 - conditional) / conditional)
    result = {"win_probability": win, "push_probability": push, "loss_probability": loss,
              "conditional_win_probability": conditional, "fair_american": fair,
              "break_even_probability": None, "raw_price_edge": None,
              "expected_profit_per_unit": None, "no_vig_edge": None,
              "status": "UNPRICED", "official_eligible": False, "stake": 0.0}
    if now >= start:
        result['status'] = 'GAME_STARTED'
        return result
    if american_odds is None:
        return result
    if isinstance(american_odds, bool) or not isfinite(american_odds) or abs(american_odds) < 100:
        raise ValueError("INVALID_AMERICAN_ODDS")
    if quote_at is None:
        result['status'] = 'QUOTE_TIME_MISSING'
        return result
    if quote_at > now:
        result['status'] = 'FUTURE_QUOTE'
        return result
    if (now - quote_at).total_seconds() > ttl_seconds:
        result['status'] = 'STALE_QUOTE'
        return result
    if conditional is None:
        result['status'] = 'ALL_PUSH'
        return result
    profit = american_odds / 100 if american_odds > 0 else 100 / -american_odds
    break_even = 1 / (1 + profit)
    ev = win * profit - loss
    result.update(break_even_probability=break_even, raw_price_edge=conditional - break_even,
                  expected_profit_per_unit=ev,
                  status='RESEARCH_POSITIVE_EV' if ev > 0 else 'RESEARCH_NO_VALUE')
    return result
