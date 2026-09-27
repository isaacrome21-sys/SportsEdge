"""Fit score-conditioned NFL scoring-composition priors from PIT-safe PBP.

This is the transparent replacement path for engineering weights in
nfl_score_td_composition.  It adapts the disclosed MySpariEdge/Spari Edge
Game Picks -> Touchdown Picks separation: historical game scoring mechanics
are learned upstream, while sportsbook prices remain downstream.

Expected input is one row per completed game/team with counts derived from
play-by-play scoring events.  nflverse/nflfastR exposes touchdown, field-goal,
extra-point, two-point-conversion and safety indicators suitable for building
these rows.  No market price is accepted here.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping, Sequence

from sports.common.ev_math import EVError, parse_utc

FORBIDDEN_MARKET_KEYS = frozenset({
    "price_american", "odds", "market_no_vig_p", "edge_probability_points",
    "ev_per_dollar", "fair_american", "sportsbook_probability", "spread",
    "total_line", "moneyline",
})


class NflScoringCompositionFitError(ValueError):
    pass


@dataclass(frozen=True)
class ScoringCompositionPrior:
    as_of: str
    training_rows: int
    counts_by_score: dict[int, dict[tuple[int, int, int, int, int], int]]


def _ts(value: Any) -> datetime:
    try:
        return parse_utc(value).astimezone(timezone.utc)
    except (EVError, TypeError, ValueError) as exc:
        raise NflScoringCompositionFitError("TIME_INVALID") from exc


def _count(row: Mapping[str, Any], key: str) -> int:
    raw = row.get(key, 0)
    if isinstance(raw, bool):
        raise NflScoringCompositionFitError(f"{key}:NONNEGATIVE_INTEGER_REQUIRED")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise NflScoringCompositionFitError(f"{key}:NONNEGATIVE_INTEGER_REQUIRED") from exc
    if not isfinite(value) or value < 0 or value != int(value):
        raise NflScoringCompositionFitError(f"{key}:NONNEGATIVE_INTEGER_REQUIRED")
    return int(value)


def fit_scoring_composition_prior(
    rows: Sequence[Mapping[str, Any]], *, as_of: datetime | str
) -> ScoringCompositionPrior:
    """Fit empirical score->composition counts using only rows known before as_of."""
    cutoff = _ts(as_of)
    if not rows:
        raise NflScoringCompositionFitError("TRAINING_ROWS_EMPTY")
    grouped: dict[int, Counter[tuple[int, int, int, int, int]]] = defaultdict(Counter)
    used = 0
    for row in rows:
        if not isinstance(row, Mapping):
            raise NflScoringCompositionFitError("TRAINING_ROW_OBJECT_REQUIRED")
        if FORBIDDEN_MARKET_KEYS.intersection(row):
            raise NflScoringCompositionFitError("MARKET_INPUT_FORBIDDEN")
        completed_at = _ts(row.get("completed_at"))
        if completed_at >= cutoff:
            raise NflScoringCompositionFitError("PIT_FUTURE_OR_SAME_TIME_ROW")
        td = _count(row, "touchdowns")
        pat = _count(row, "extra_points_made")
        two = _count(row, "two_point_made")
        fg = _count(row, "field_goals_made")
        safety = _count(row, "safeties")
        # A team cannot make more ordinary post-TD tries than its TD count.
        if pat + two > td:
            raise NflScoringCompositionFitError("POST_TD_TRIES_EXCEED_TOUCHDOWNS")
        score = _count(row, "score")
        reconstructed = 6 * td + pat + 2 * two + 3 * fg + 2 * safety
        if reconstructed != score:
            raise NflScoringCompositionFitError("SCORING_COMPOSITION_DOES_NOT_RECONSTRUCT_SCORE")
        grouped[score][(td, pat, two, fg, safety)] += 1
        used += 1
    return ScoringCompositionPrior(
        as_of=cutoff.isoformat(),
        training_rows=used,
        counts_by_score={score: dict(counter) for score, counter in grouped.items()},
    )
