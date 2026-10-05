"""Bridge labeled NFL_SCORE_COUNTS_G1 history into the existing TD scoring prior.

The score-count training rows already contain factual scoring components.  This
adapter selects only those labels, reconstructs final team score, and supplies a
conservative completion timestamp (kickoff + 24h) for fully historical games.
Sportsbook or market fields are never forwarded.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any, Mapping, Sequence

from sportsedge.nfl_scoring_composition_fit import (
    ScoringCompositionPrior,
    fit_scoring_composition_prior,
)


class ScoreCountScoringPriorBridgeError(ValueError):
    pass


def _utc(value: Any, field: str) -> datetime:
    try:
        dt = datetime.fromisoformat(str(value or "").strip().replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ScoreCountScoringPriorBridgeError(f"{field}:TIMESTAMP_REQUIRED") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ScoreCountScoringPriorBridgeError(f"{field}:TIMEZONE_REQUIRED")
    return dt.astimezone(timezone.utc)


def _count(row: Mapping[str, Any], key: str) -> int:
    raw = row.get(key)
    if isinstance(raw, bool):
        raise ScoreCountScoringPriorBridgeError(f"{key}:NONNEGATIVE_INTEGER_REQUIRED")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ScoreCountScoringPriorBridgeError(f"{key}:NONNEGATIVE_INTEGER_REQUIRED") from exc
    if not isfinite(value) or value < 0 or value != int(value):
        raise ScoreCountScoringPriorBridgeError(f"{key}:NONNEGATIVE_INTEGER_REQUIRED")
    return int(value)


def score_count_training_rows_to_composition_rows(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Project labeled score-count rows into the market-blind composition schema."""
    if not rows:
        raise ScoreCountScoringPriorBridgeError("TRAINING_ROWS_EMPTY")
    out: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ScoreCountScoringPriorBridgeError(f"row[{idx}]:OBJECT_REQUIRED")
        start = _utc(row.get("game_start_ts"), f"row[{idx}].game_start_ts")
        offense_td = _count(row, "offense_touchdowns")
        def_st_td = _count(row, "def_st_touchdowns")
        pat = _count(row, "pat_made")
        two = _count(row, "two_point_made")
        fg = _count(row, "made_field_goals")
        safety = _count(row, "safeties")
        touchdowns = offense_td + def_st_td
        score = 6 * touchdowns + pat + 2 * two + 3 * fg + 2 * safety
        out.append({
            "completed_at": (start + timedelta(days=1)).isoformat(),
            "touchdowns": touchdowns,
            "extra_points_made": pat,
            "two_point_made": two,
            "field_goals_made": fg,
            "safeties": safety,
            "score": score,
        })
    return out


def fit_scoring_prior_from_score_count_training_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    as_of: datetime | str,
) -> ScoringCompositionPrior:
    """Fit the existing empirical exact-score prior from score-count history."""
    projected = score_count_training_rows_to_composition_rows(rows)
    return fit_scoring_composition_prior(projected, as_of=as_of)


__all__ = [
    "ScoreCountScoringPriorBridgeError",
    "fit_scoring_prior_from_score_count_training_rows",
    "score_count_training_rows_to_composition_rows",
]
