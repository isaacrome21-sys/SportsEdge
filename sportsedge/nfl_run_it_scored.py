"""Score-B bettor-facing wrapper for NFL game RUN IT.

Design reference: the user-supplied MySpariEdge NFL Props Edge Model, NFL Prop
Picks Model, Touchdown Picks Model and Game Picks Model materials keep model /
role quality visible alongside, but distinct from, fair-price market economics.
This module adapts that disclosed presentation pattern without copying hidden
MySpariEdge formulas or weights.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping, Sequence

from sportsedge.nfl_run_it import CardPick, RunItCard, run_it
from sportsedge.nfl_run_it_score_binding import bind_score_b
from sportsedge.nfl_run_it_scoring import SCORE_LABEL


def run_it_scored(
    quotes: Sequence[Mapping[str, Any]],
    estimates: Sequence[Mapping[str, Any]],
    qualification_snapshots: Sequence[Mapping[str, Any]],
    **kwargs: Any,
) -> RunItCard:
    """Run game pricing, then attach locked Score B by exact row identity.

    Economics and candidate ordering are produced by ``run_it`` first. Score B
    is attached afterward from PIT-safe qualification snapshots, so price, EV
    and edge cannot influence Score or card order. Every surviving bettor-facing
    row must have an exact qualification snapshot; missing identity fails closed.
    """
    card = run_it(quotes, estimates, **kwargs)
    rows = [asdict(p) for p in card.picks]
    bound = bind_score_b(rows, qualification_snapshots)
    picks = tuple(
        CardPick(
            **{
                **row,
                "rank": idx,
                "score_label": SCORE_LABEL,
            }
        )
        for idx, row in enumerate(bound, start=1)
    )
    return RunItCard(
        schema=card.schema,
        sport=card.sport,
        picks=picks,
        omitted=card.omitted,
        empty_reason=card.empty_reason,
        authority_footer=card.authority_footer,
    )
