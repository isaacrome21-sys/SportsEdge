"""Score-B bettor-facing wrapper for NFL game RUN IT.

Economics and candidate ordering are produced by run_it first. Score B is
attached afterward from PIT-safe qualification snapshots. Missing identity
fails closed. Score cannot change EV, edge or rank.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from sportsedge.nfl_run_it import CardPick, RunItCard, run_it
from sportsedge.nfl_run_it_score_binding import bind_score_b
from sportsedge.nfl_run_it_scoring import SCORE_LABEL


@dataclass(frozen=True)
class ScoredCardPick(CardPick):
    """A canonical RUN IT pick with additive, non-economic Score-B fields."""

    score_0_100: int
    score_label: str = SCORE_LABEL


def run_it_scored(
    quotes: Sequence[Mapping[str, Any]],
    estimates: Sequence[Mapping[str, Any]],
    qualification_snapshots: Sequence[Mapping[str, Any]],
    **kwargs: Any,
) -> RunItCard:
    card = run_it(quotes, estimates, **kwargs)
    rows = [asdict(pick) for pick in card.picks]
    bound = bind_score_b(rows, qualification_snapshots)

    scored_picks = tuple(
        ScoredCardPick(
            **asdict(pick),
            score_0_100=int(row["score_0_100"]),
        )
        for pick, row in zip(card.picks, bound)
    )

    return RunItCard(
        schema=card.schema,
        sport=card.sport,
        picks=scored_picks,
        omitted=card.omitted,
        empty_reason=card.empty_reason,
        authority_footer=card.authority_footer,
    )
