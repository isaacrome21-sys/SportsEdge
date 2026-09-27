"""NBA sportsbook quote binding and bettor-facing score contract.

Quotes are bound to an already-computed model probability. They never create
Model_P. Score is a qualification/evidence-quality surface only; EV and edge
remain separate ranking fields and never feed Score.
"""
from dataclasses import dataclass
from datetime import datetime
import math

from .pricing import NBAFairPrice, expected_value


@dataclass(frozen=True)
class NBAQuote:
    game_id: str
    market: str
    selection: str
    line: float | None
    decimal_odds: float
    book: str
    captured_at: datetime

    def validate(self) -> None:
        if not all((self.game_id, self.market, self.selection, self.book)):
            raise ValueError("quote identity/book are required")
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError("captured_at must be timezone-aware")
        if not math.isfinite(self.decimal_odds) or self.decimal_odds <= 1.0:
            raise ValueError("decimal_odds must be finite and > 1")
        if self.line is not None and not math.isfinite(self.line):
            raise ValueError("line must be finite when present")


@dataclass(frozen=True)
class NBABoundEdge:
    quote: NBAQuote
    fair: NBAFairPrice
    ev: float
    score: int
    score_version: str = "NBA_RUN_IT_SCORE_RULE_B_V2"


def bind_quote(
    quote: NBAQuote,
    fair: NBAFairPrice,
    *,
    as_of: datetime,
    max_age_seconds: int = 300,
    model_quality: float,
    context_quality: float,
) -> NBABoundEdge:
    quote.validate()
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    age=(as_of-quote.captured_at).total_seconds()
    if age < 0:
        raise ValueError("quote cannot be captured after binding time")
    if max_age_seconds < 0 or age > max_age_seconds:
        raise ValueError("stale sportsbook quote")
    for name,value in (("model_quality",model_quality),("context_quality",context_quality)):
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} must be in [0, 1]")
    ev=expected_value(fair,quote.decimal_odds)
    # Rule B: Score communicates qualification/evidence quality only. Market
    # attractiveness is expressed by fair probability/price and EV, which callers
    # may rank separately. This prevents price-derived EV from masquerading as
    # model confidence.
    quality=math.sqrt(model_quality*context_quality)
    score=round(max(0.0,min(100.0,100.0*quality)))
    return NBABoundEdge(quote,fair,ev,score)
