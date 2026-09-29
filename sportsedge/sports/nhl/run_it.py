"""NHL RUN IT card assembly with explicit capability and quote binding.

Ordinary output is bettor-facing model output, not an OFFICIAL/Truth-Gate claim.
Only supplied model probability mass and timestamped book quotes can produce
price economics. A 0-100 Score additionally requires an upstream qualification
score; price, edge, EV and win probability never manufacture Score.
"""
from dataclasses import dataclass
from .market_capabilities import capability_for
from .markets import OutcomeProbability
from .pricing import NHLQuote, NHLPrice, price_outcome


@dataclass(frozen=True)
class NHLRunItRow:
    market: str
    selection: str
    status: str
    price: NHLPrice | None
    reason: str


def run_it_row(
    market: str,
    selection: str,
    outcome: OutcomeProbability | None,
    quote: NHLQuote | None,
    *,
    qualification_score: float | None = None,
) -> NHLRunItRow:
    cap = capability_for(market)
    if cap.status == "NO_ENGINE":
        return NHLRunItRow(cap.market, selection, "UNSUPPORTED", None, cap.reason)
    if outcome is None:
        return NHLRunItRow(cap.market, selection, "NO_MODEL_PROBABILITY", None, "No coherent model probability supplied.")
    if quote is None:
        return NHLRunItRow(cap.market, selection, "NO_MARKET_QUOTE", None, "No timestamped market quote supplied.")
    if quote.market.strip().upper() != cap.market or quote.selection != selection:
        raise ValueError("quote binding mismatch")
    priced = price_outcome(outcome, quote, qualification_score=qualification_score)
    if priced.qualification_score is None:
        return NHLRunItRow(
            cap.market,
            selection,
            "PRICED_NO_SCORE",
            priced,
            "Price economics available; upstream qualification score not supplied.",
        )
    return NHLRunItRow(cap.market, selection, "SCORED", priced, "")


def rank_scored(rows: list[NHLRunItRow]) -> list[NHLRunItRow]:
    """Rank qualified scores first; EV may break equal-score presentation ties."""
    status_order = {"SCORED": 2, "PRICED_NO_SCORE": 1}
    return sorted(
        rows,
        key=lambda r: (
            status_order.get(r.status, 0),
            r.price.qualification_score if r.price and r.price.qualification_score is not None else -1.0,
            r.price.expected_value if r.price else float("-inf"),
        ),
        reverse=True,
    )
