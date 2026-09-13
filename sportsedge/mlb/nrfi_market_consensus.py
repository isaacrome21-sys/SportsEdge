from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from statistics import median
from typing import Iterable, Mapping, Sequence


DEFAULT_BOOK_WEIGHTS: dict[str, float] = {
    "pinnacle": 1.50,
    "circa": 1.40,
    "bookmaker": 1.30,
    "betonline": 1.10,
    "draftkings": 1.00,
    "fanduel": 1.00,
    "betmgm": 0.95,
    "caesars": 0.95,
}


@dataclass(frozen=True)
class TwoWayQuote:
    sportsbook: str
    nrfi_american: int
    yrfi_american: int
    captured_at_utc: str | None = None


@dataclass(frozen=True)
class DeviggedQuote:
    sportsbook: str
    nrfi_fair_prob: float
    yrfi_fair_prob: float
    overround: float
    weight: float
    captured_at_utc: str | None = None


@dataclass(frozen=True)
class MarketConsensus:
    nrfi_consensus_prob: float
    yrfi_consensus_prob: float
    weighted_mean_nrfi: float
    median_nrfi: float
    dispersion: float
    books_used: int
    devigged_quotes: tuple[DeviggedQuote, ...]


@dataclass(frozen=True)
class MarketEdge:
    side: str
    model_prob: float
    market_prob: float
    edge_prob: float
    offered_american: int
    expected_value: float


def american_to_implied_prob(american: int) -> float:
    if american == 0:
        raise ValueError("American odds cannot be zero")
    if american > 0:
        return 100.0 / (american + 100.0)
    return (-american) / ((-american) + 100.0)


def american_profit_per_unit(american: int) -> float:
    if american == 0:
        raise ValueError("American odds cannot be zero")
    if american > 0:
        return american / 100.0
    return 100.0 / (-american)


def proportional_devig(nrfi_american: int, yrfi_american: int) -> tuple[float, float, float]:
    """Remove two-way hold proportionally.

    This is deliberately transparent and deterministic. It is a market-consensus
    feature layer, not a claim that proportional devig is the uniquely correct
    bookmaker fair-pricing model.
    """
    p_nrfi = american_to_implied_prob(nrfi_american)
    p_yrfi = american_to_implied_prob(yrfi_american)
    total = p_nrfi + p_yrfi
    if total <= 0 or not isfinite(total):
        raise ValueError("Invalid two-way market")
    return p_nrfi / total, p_yrfi / total, total - 1.0


def _book_weight(book: str, weights: Mapping[str, float] | None) -> float:
    mapping = weights or DEFAULT_BOOK_WEIGHTS
    weight = float(mapping.get(book.strip().lower(), 1.0))
    if not isfinite(weight) or weight <= 0:
        raise ValueError(f"Invalid book weight for {book}: {weight}")
    return weight


def build_consensus(
    quotes: Iterable[TwoWayQuote],
    *,
    book_weights: Mapping[str, float] | None = None,
    shrink_to_median: float = 0.20,
) -> MarketConsensus:
    """Build a de-vigged, sharp-weighted NRFI/YRFI market consensus.

    `shrink_to_median` limits the ability of a single heavily weighted outlier to
    dominate consensus. 0 means weighted mean only; 1 means median only.
    """
    if not 0.0 <= shrink_to_median <= 1.0:
        raise ValueError("shrink_to_median must be between 0 and 1")

    rows: list[DeviggedQuote] = []
    for quote in quotes:
        nrfi, yrfi, overround = proportional_devig(quote.nrfi_american, quote.yrfi_american)
        rows.append(
            DeviggedQuote(
                sportsbook=quote.sportsbook,
                nrfi_fair_prob=nrfi,
                yrfi_fair_prob=yrfi,
                overround=overround,
                weight=_book_weight(quote.sportsbook, book_weights),
                captured_at_utc=quote.captured_at_utc,
            )
        )

    if len(rows) < 2:
        raise ValueError("At least two sportsbooks are required for consensus")

    total_weight = sum(r.weight for r in rows)
    weighted = sum(r.nrfi_fair_prob * r.weight for r in rows) / total_weight
    med = median(r.nrfi_fair_prob for r in rows)
    consensus = (1.0 - shrink_to_median) * weighted + shrink_to_median * med
    dispersion = max(r.nrfi_fair_prob for r in rows) - min(r.nrfi_fair_prob for r in rows)

    return MarketConsensus(
        nrfi_consensus_prob=consensus,
        yrfi_consensus_prob=1.0 - consensus,
        weighted_mean_nrfi=weighted,
        median_nrfi=med,
        dispersion=dispersion,
        books_used=len(rows),
        devigged_quotes=tuple(rows),
    )


def price_edge(
    *,
    model_nrfi_prob: float,
    consensus: MarketConsensus,
    offered_nrfi_american: int,
) -> MarketEdge:
    """Compare baseball-model probability to consensus and tradable price."""
    if not 0.0 < model_nrfi_prob < 1.0:
        raise ValueError("model_nrfi_prob must be in (0,1)")
    profit = american_profit_per_unit(offered_nrfi_american)
    ev = model_nrfi_prob * profit - (1.0 - model_nrfi_prob)
    return MarketEdge(
        side="NRFI",
        model_prob=model_nrfi_prob,
        market_prob=consensus.nrfi_consensus_prob,
        edge_prob=model_nrfi_prob - consensus.nrfi_consensus_prob,
        offered_american=offered_nrfi_american,
        expected_value=ev,
    )


def movement_signal(
    opening: MarketConsensus,
    current: MarketConsensus,
    *,
    min_move_prob: float = 0.01,
) -> str:
    """Classify consensus movement without using it as promotion evidence."""
    move = current.nrfi_consensus_prob - opening.nrfi_consensus_prob
    if move >= min_move_prob:
        return "STEAM_NRFI"
    if move <= -min_move_prob:
        return "STEAM_YRFI"
    return "NO_MEANINGFUL_STEAM"


def release_gate(
    edge: MarketEdge,
    consensus: MarketConsensus,
    *,
    min_model_market_edge: float = 0.015,
    min_expected_value: float = 0.02,
    max_dispersion: float = 0.045,
    min_books: int = 3,
) -> tuple[bool, tuple[str, ...]]:
    """Fail closed unless both model edge and tradable EV clear thresholds."""
    reasons: list[str] = []
    if consensus.books_used < min_books:
        reasons.append("INSUFFICIENT_BOOKS")
    if consensus.dispersion > max_dispersion:
        reasons.append("MARKET_DISAGREEMENT_HIGH")
    if edge.edge_prob < min_model_market_edge:
        reasons.append("MODEL_MARKET_EDGE_TOO_SMALL")
    if edge.expected_value < min_expected_value:
        reasons.append("PRICE_EV_TOO_SMALL")
    return not reasons, tuple(reasons)


def clv_probability_delta(entry_consensus_prob: float, closing_consensus_prob: float, side: str = "NRFI") -> float:
    """Probability-space CLV. Positive means market moved toward the entry side."""
    if side.upper() == "NRFI":
        return closing_consensus_prob - entry_consensus_prob
    if side.upper() == "YRFI":
        return entry_consensus_prob - closing_consensus_prob
    raise ValueError("side must be NRFI or YRFI")
