"""NHL RUN IT card assembly with explicit capability and quote binding.

Ordinary output is bettor-facing model output, not an OFFICIAL/Truth-Gate claim.
Only supplied model probability mass and timestamped book quotes can produce a score.
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


def run_it_row(market: str, selection: str, outcome: OutcomeProbability | None, quote: NHLQuote | None) -> NHLRunItRow:
    cap=capability_for(market)
    if cap.status == "NO_ENGINE":
        return NHLRunItRow(cap.market, selection, "UNSUPPORTED", None, cap.reason)
    if outcome is None:
        return NHLRunItRow(cap.market, selection, "NO_MODEL_PROBABILITY", None, "No coherent model probability supplied.")
    if quote is None:
        return NHLRunItRow(cap.market, selection, "NO_MARKET_QUOTE", None, "No timestamped market quote supplied.")
    if quote.market.strip().upper() != cap.market or quote.selection != selection:
        raise ValueError("quote binding mismatch")
    return NHLRunItRow(cap.market, selection, "SCORED", price_outcome(outcome, quote), "")


def rank_scored(rows: list[NHLRunItRow]) -> list[NHLRunItRow]:
    """Sort scored candidates by transparent score then EV; retain unsupported rows last."""
    return sorted(rows, key=lambda r: (
        r.status == "SCORED",
        r.price.edge_score if r.price else -1,
        r.price.expected_value if r.price else float("-inf"),
    ), reverse=True)
