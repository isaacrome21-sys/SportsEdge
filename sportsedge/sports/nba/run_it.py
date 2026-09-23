"""NBA RUN IT bettor-facing card assembly.

This surface reports only already-computed, fresh bound model edges. It does not
create model probabilities, infer missing markets, or promote unsupported markets.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from .binding import NBABoundEdge
from .market_capabilities import capability_for


@dataclass(frozen=True)
class NBARunItRow:
    game_id: str
    market: str
    selection: str
    line: float | None
    book: str
    model_probability: float
    fair_decimal: float
    market_decimal: float
    ev: float
    score: int
    score_version: str


@dataclass(frozen=True)
class NBARunItCard:
    generated_at: datetime
    rows: tuple[NBARunItRow, ...]
    unsupported_markets: tuple[str, ...]


def build_run_it_card(
    edges: Iterable[NBABoundEdge],
    *,
    generated_at: datetime,
    requested_markets: Iterable[str] = (),
    minimum_score: int = 0,
) -> NBARunItCard:
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")
    if not 0 <= minimum_score <= 100:
        raise ValueError("minimum_score must be in [0, 100]")

    requested=tuple(dict.fromkeys(m.strip().upper() for m in requested_markets if m.strip()))
    unsupported=tuple(m for m in requested if capability_for(m).status == "NO_ENGINE")
    rows=[]
    for edge in edges:
        q=edge.quote
        cap=capability_for(q.market)
        if cap.status == "NO_ENGINE":
            continue
        if q.captured_at > generated_at:
            raise ValueError("card cannot contain a future quote")
        if not 0 <= edge.score <= 100:
            raise ValueError("bound score must be in [0, 100]")
        if edge.score < minimum_score:
            continue
        rows.append(NBARunItRow(
            q.game_id,q.market,q.selection,q.line,q.book,
            edge.fair.win_probability,edge.fair.fair_decimal,q.decimal_odds,
            edge.ev,edge.score,edge.score_version,
        ))
    # Stable presentation: score first, then EV, then identity. This is a display
    # ordering, not a claim that the score is win probability.
    rows.sort(key=lambda r:(-r.score,-r.ev,r.game_id,r.market,r.selection,r.book))
    return NBARunItCard(generated_at,tuple(rows),unsupported)
