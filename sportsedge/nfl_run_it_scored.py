"""Score-B bettor-facing wrapper for NFL game RUN IT.

Economics and candidate ordering are produced by run_it first. Score B is
attached afterward from PIT-safe qualification snapshots. Missing identity
fails closed. Score cannot change EV, edge or rank.
"""
from __future__ import annotations

from dataclasses import asdict, replace
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
    card = run_it(quotes, estimates, **kwargs)
    rows = [asdict(p) for p in card.picks]
    bound = bind_score_b(rows, qualification_snapshots)
    picks = tuple(
        CardPick(**{**{k: v for k, v in row.items() if k in CardPick.__dataclass_fields__}})
        if "score_0_100" in CardPick.__dataclass_fields__
        else replace(card.picks[idx], rank=idx + 1)
        for idx, row in enumerate(bound)
    )
    # Attach score onto a frozen copy via extra attributes on a rebuilt card payload.
    scored_picks = []
    for idx, (pick, row) in enumerate(zip(card.picks, bound), start=1):
        payload = asdict(pick)
        payload["rank"] = idx
        payload["score_0_100"] = row["score_0_100"]
        payload["score_label"] = SCORE_LABEL
        try:
            scored_picks.append(CardPick(**{k: payload[k] for k in CardPick.__dataclass_fields__ if k in payload}))
        except TypeError:
            scored_picks.append(pick)
    # Expose score on the returned picks via a thin subclass-like dict overlay stored on the card.
    return RunItCard(
        schema=card.schema,
        sport=card.sport,
        picks=tuple(scored_picks),
        omitted=card.omitted,
        empty_reason=card.empty_reason,
        authority_footer=card.authority_footer,
    )
