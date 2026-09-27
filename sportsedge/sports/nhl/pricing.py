"""NHL fair-price, EV and bettor-facing RUN IT score helpers.

Scores are transparent presentation scores, not calibrated win probabilities or
historical performance claims. Pricing preserves push mass.
"""
from dataclasses import dataclass
import math
from datetime import datetime, timezone
from .markets import OutcomeProbability


@dataclass(frozen=True)
class NHLQuote:
    market: str
    selection: str
    american_odds: int
    book: str
    captured_at: str
    source_version: str = "UNVERSIONED"

    def validate(self) -> None:
        if not self.market or not self.selection or not self.book or not self.captured_at or not self.source_version:
            raise ValueError("market/selection/book/captured_at/source_version are required")
        dt = datetime.fromisoformat(self.captured_at.replace("Z", "+00:00"))
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError("quote captured_at must be timezone-aware")
        if -100 < self.american_odds < 100:
            raise ValueError("American odds must be <= -100 or >= +100")


@dataclass(frozen=True)
class NHLPrice:
    model_win: float
    model_push: float
    model_loss: float
    fair_probability: float
    fair_american: int
    expected_value: float
    edge_score: int
    score_label: str = "TRANSPARENT_EV_SCORE_V1"


def american_profit(odds: int) -> float:
    if -100 < odds < 100:
        raise ValueError("American odds must be <= -100 or >= +100")
    return odds / 100.0 if odds > 0 else 100.0 / abs(odds)


def american_from_probability(probability: float) -> int:
    if not 0.0 < probability < 1.0:
        raise ValueError("probability must be strictly between 0 and 1")
    if probability >= 0.5:
        return int(round(-100.0 * probability / (1.0 - probability)))
    return int(round(100.0 * (1.0 - probability) / probability))


def price_outcome(outcome: OutcomeProbability, quote: NHLQuote) -> NHLPrice:
    quote.validate()
    decisive = outcome.win + outcome.loss
    if decisive <= 0:
        raise ValueError("cannot price an all-push outcome")
    fair_probability = outcome.win / decisive
    ev = outcome.win * american_profit(quote.american_odds) - outcome.loss
    # Presentation transform only: 50 is zero EV, each +1% unit EV adds 2 points.
    # It is intentionally bounded and must never be presented as win probability.
    score = int(round(max(0.0, min(100.0, 50.0 + 200.0 * ev))))
    return NHLPrice(
        outcome.win, outcome.push, outcome.loss, fair_probability,
        american_from_probability(fair_probability), ev, score,
    )


def validate_quote_freshness(quote: NHLQuote, *, as_of: str, max_age_seconds: int) -> None:
    """Fail closed on future or stale quotes relative to an explicit run timestamp."""
    quote.validate()
    if max_age_seconds < 0:
        raise ValueError("max_age_seconds must be nonnegative")
    captured = datetime.fromisoformat(quote.captured_at.replace("Z", "+00:00")).astimezone(timezone.utc)
    current = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    current = current.astimezone(timezone.utc)
    age = (current - captured).total_seconds()
    if age < 0:
        raise ValueError("quote captured_at is in the future")
    if age > max_age_seconds:
        raise ValueError("stale market quote")
