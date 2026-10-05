"""Frozen opening-drive/first-score structural metrics for the NFL challenger.

Reference-path semantics are frozen before empirical holdout evaluation. This
module has no acquisition or promotion authority.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .nfl_possession_challenger import PossessionPath


def summarize_reference_opening_metrics(paths: Iterable[PossessionPath]) -> dict[str,Any]:
    """Summarize opening-drive scoring and first-score receiver probability.

    Opening-drive scoring means the opening-kickoff receiver scores positive
    offensive points on its first credited possession. A safety credits the
    defense and therefore does not count as an opening-receiver drive score.

    First-score opening-receiver rate is conditional on paths with at least one
    score. Scoreless paths are retained and reported separately rather than
    being silently treated as either side's first score.
    """
    data=tuple(paths)
    if not data:
        raise ValueError("CHALLENGER_REFERENCE_PATHS_EMPTY")
    if any(not isinstance(path,PossessionPath) for path in data):
        raise TypeError("POSSESSION_PATH_REQUIRED")

    opening_scores=0
    scored_paths=0
    first_score_by_opening_receiver=0
    scoreless=0

    for path in data:
        first_half=[possession for possession in path.possessions if possession.half==1]
        if not first_half:
            raise ValueError("CHALLENGER_OPENING_POSSESSION_MISSING")
        opening=first_half[0]
        if opening.offense!=path.opening_receiver:
            raise ValueError("CHALLENGER_OPENING_RECEIVER_PATH_MISMATCH")
        if opening.points>0:
            opening_scores+=1

        first_scorer=None
        for possession in path.possessions:
            if possession.points>0:
                first_scorer=possession.offense
                break
            if possession.points<0:
                first_scorer=possession.defense
                break
        if first_scorer is None:
            scoreless+=1
            continue
        scored_paths+=1
        if first_scorer==path.opening_receiver:
            first_score_by_opening_receiver+=1

    return {
        "schema":"NFL_CHALLENGER_OPENING_METRICS_V1",
        "path_count":len(data),
        "scored_path_count":scored_paths,
        "scoreless_path_count":scoreless,
        "opening_drive_scoring_rate":opening_scores/len(data),
        "first_score_opening_receiver_rate":(
            first_score_by_opening_receiver/scored_paths if scored_paths else None
        ),
        "first_score_denominator":"paths_with_at_least_one_score",
        "opening_drive_definition":"positive_points_by_opening_receiver_on_first_possession",
        "safety_scoring_team":"defense",
        "authority":"NONE_RESEARCH_ONLY",
        "promotion_authority":False,
        "truth_gate_authority":False,
        "official_authority":False,
    }
