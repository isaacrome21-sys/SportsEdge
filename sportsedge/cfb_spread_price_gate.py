"""Fail-closed CFB spread quote math; no model, validation, or PLAY authority.

Inputs are a model's three-way probabilities for cover/push/loss and an
observed American price. This module deliberately does not manufacture them.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class SpreadAssessment:
    status: str
    reason: str
    expected_profit_per_unit: float | None
    break_even_conditional_cover: float | None
    conditional_cover: float | None


def assess_spread(
    *, price_american: int | None,
    cover_probability: float | None,
    push_probability: float | None,
    loss_probability: float | None,
    quote_current: bool,
    model_verified: bool,
    illinois_college_team: bool = False,
    straight_price_floor: int = -165,
) -> SpreadAssessment:
    def blocked(reason: str) -> SpreadAssessment:
        return SpreadAssessment("PASS", reason, None, None, None)

    if illinois_college_team:
        return blocked("ILLINOIS_COLLEGE_EXCLUDED")
    if not quote_current:
        return blocked("QUOTE_NOT_CURRENT")
    if not model_verified:
        return blocked("MODEL_NOT_VERIFIED")
    if type(price_american) is not int or -100 < price_american < 100 or price_american == 0:
        return blocked("PRICE_INVALID")
    if price_american < straight_price_floor:
        return blocked("STRAIGHT_PRICE_CAP")
    probs = (cover_probability, push_probability, loss_probability)
    if any(type(p) not in (float, int) or not isfinite(p) or p < 0 or p > 1 for p in probs):
        return blocked("PROBABILITIES_INVALID")
    if abs(sum(probs) - 1.0) > 1e-6:
        return blocked("PROBABILITIES_NOT_NORMALIZED")
    decisive = cover_probability + loss_probability
    if decisive <= 0:
        return blocked("ALL_PUSH_NO_DECISION")
    payout = price_american / 100 if price_american > 0 else 100 / abs(price_american)
    ev = cover_probability * payout - loss_probability
    threshold = 1 / (1 + payout)
    conditional = cover_probability / decisive
    return SpreadAssessment(
        "PLAY" if ev > 0 else "PASS",
        "POSITIVE_EV" if ev > 0 else "NONPOSITIVE_EV",
        ev,
        threshold,
        conditional,
    )
