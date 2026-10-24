"""Fail-closed CFB spread pricing; no model-validation or promotion authority.

The caller may submit an independent projection and an exact paired quote.
This helper computes push-aware EV but does not independently authenticate
model promotion or provenance: it therefore cannot issue a PLAY.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import floor, isfinite


MAX_QUOTE_AGE_SECONDS = 180.0
MAX_CAPTURE_SPAN_SECONDS = 150.0


@dataclass(frozen=True)
class SpreadAssessment:
    status: str
    reason: str
    expected_profit_per_unit: float | None
    break_even_conditional_cover: float | None
    conditional_cover: float | None
    no_vig_market_cover: float | None
    no_vig_edge: float | None
    playable_to_american: int | None


def _valid_price(price: object) -> bool:
    return type(price) is int and not (-100 < price < 100)


def _implied_probability(price: int) -> float:
    return 100 / (100 + price) if price > 0 else abs(price) / (abs(price) + 100)


def _utc_instant(value: object) -> datetime | None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        return None
    return value.astimezone(timezone.utc)


def _playable_to(*, cover: float, loss: float, price_floor: int) -> int | None:
    if cover <= 0:
        return None
    if loss == 0:
        return price_floor
    fair_profit = loss / cover
    if fair_profit >= 1:
        first_profitable = floor(100 * fair_profit) + 1
    else:
        first_profitable = floor(-100 / fair_profit) + 1
    return max(first_profitable, price_floor)


def assess_spread(
    *,
    line: float | int | None,
    opposite_line: float | int | None,
    price_american: int | None,
    opposite_price_american: int | None,
    side_quoted_at: datetime | None,
    opposite_quoted_at: datetime | None,
    as_of: datetime | None,
    event_start: datetime | None,
    sportsbook: str | None,
    source_ref: str | None,
    cover_probability: float | None,
    push_probability: float | None,
    loss_probability: float | None,
    model_verified: bool,
    model_market_blind: bool,
    model_id: str | None,
    illinois_college_team: bool = False,
    straight_price_floor: int = -165,
) -> SpreadAssessment:
    def blocked(reason: str) -> SpreadAssessment:
        return SpreadAssessment("PASS", reason, None, None, None, None, None, None)

    if illinois_college_team:
        return blocked("ILLINOIS_COLLEGE_EXCLUDED")
    if model_verified is not True:
        return blocked("MODEL_NOT_VERIFIED")
    if model_market_blind is not True:
        return blocked("MODEL_NOT_MARKET_BLIND")
    if not isinstance(model_id, str) or not model_id.strip():
        return blocked("MODEL_ID_MISSING")
    if sportsbook != "DraftKings":
        return blocked("SPORTSBOOK_NOT_DRAFTKINGS")
    if not isinstance(source_ref, str) or not source_ref.strip():
        return blocked("SOURCE_REF_MISSING")
    if not _valid_price(price_american) or not _valid_price(opposite_price_american):
        return blocked("PAIRED_PRICE_INVALID")
    if price_american < straight_price_floor:
        return blocked("STRAIGHT_PRICE_CAP")

    if (
        type(line) not in (float, int)
        or type(opposite_line) not in (float, int)
        or not isfinite(line)
        or not isfinite(opposite_line)
        or abs(float(line) + float(opposite_line)) > 1e-9
    ):
        return blocked("PAIRED_LINE_MISMATCH")

    side_time = _utc_instant(side_quoted_at)
    opposite_time = _utc_instant(opposite_quoted_at)
    evaluation_time = _utc_instant(as_of)
    kickoff_time = _utc_instant(event_start)
    if side_time is None or opposite_time is None or evaluation_time is None:
        return blocked("QUOTE_TIMESTAMP_INVALID")
    if kickoff_time is None or kickoff_time <= evaluation_time:
        return blocked("EVENT_STARTED_OR_INVALID")
    ages = (
        (evaluation_time - side_time).total_seconds(),
        (evaluation_time - opposite_time).total_seconds(),
    )
    if any(age < 0 for age in ages):
        return blocked("QUOTE_FROM_FUTURE")
    if any(age > MAX_QUOTE_AGE_SECONDS for age in ages):
        return blocked("QUOTE_STALE")
    if abs((side_time - opposite_time).total_seconds()) > MAX_CAPTURE_SPAN_SECONDS:
        return blocked("PAIRED_CAPTURE_SPAN_EXCEEDED")

    probs = (cover_probability, push_probability, loss_probability)
    if any(type(p) not in (float, int) or not isfinite(p) or p < 0 or p > 1 for p in probs):
        return blocked("PROBABILITIES_INVALID")
    if abs(sum(probs) - 1.0) > 1e-6:
        return blocked("PROBABILITIES_NOT_NORMALIZED")
    decisive = cover_probability + loss_probability
    if decisive <= 0:
        return blocked("ALL_PUSH_NO_DECISION")

    payout = price_american / 100 if price_american > 0 else 100 / abs(price_american)
    expected_profit = cover_probability * payout - loss_probability
    break_even = 1 / (1 + payout)
    conditional_cover = cover_probability / decisive

    side_implied = _implied_probability(price_american)
    opposite_implied = _implied_probability(opposite_price_american)
    no_vig_market_cover = side_implied / (side_implied + opposite_implied)
    no_vig_edge = conditional_cover - no_vig_market_cover
    playable_to = _playable_to(
        cover=cover_probability,
        loss=loss_probability,
        price_floor=straight_price_floor,
    )

    if expected_profit <= 0:
        status, reason = "PASS", "NONPOSITIVE_EV"
    elif no_vig_edge <= 0:
        status, reason = "PASS", "NONPOSITIVE_MARKET_EDGE"
    else:
        # Caller booleans and free-text model IDs cannot establish official
        # registry approval. Preserve the arithmetic as a WATCH only.
        status, reason = "WATCH", "POSITIVE_EV_MODEL_AUTHORITY_UNVERIFIED"

    return SpreadAssessment(
        status,
        reason,
        expected_profit,
        break_even,
        conditional_cover,
        no_vig_market_cover,
        no_vig_edge,
        playable_to,
    )
