"""Football model-promotion stages from FOOTBALL_ROADMAP §6.

This module deliberately contains no ROI promotion criterion. Promotion is
per sport/market and culminates in observed no-vig CLV evidence.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FootballPromotionEvidence:
    math_valid: bool
    fold_wins: int
    fold_total: int
    ci_attested: bool
    calibration_max_bin_deviation: float
    calibration_threshold: float
    logged_plays: int
    mean_clv: float
    clv_t_stat: float


def evaluate_football_promotion(e: FootballPromotionEvidence) -> str:
    if not e.math_valid:
        return "BLOCKED_MATH"

    stage = "VALIDATED_MATH"
    if e.fold_total <= 0 or e.fold_wins / e.fold_total < 0.65:
        return stage

    stage = "PRODUCTION_LOGIC_PASS"
    if (not e.ci_attested) or e.calibration_max_bin_deviation > e.calibration_threshold:
        return stage

    stage = "CI_ATTESTED"
    if e.logged_plays < 200 or e.mean_clv <= 0.0 or e.clv_t_stat <= 2.0:
        return stage

    return "DEPLOYED"


def official_candidates(candidates: list[dict], stage: str) -> list[dict]:
    """Fail closed: only DEPLOYED sport/market lanes can emit official plays."""
    if stage != "DEPLOYED":
        return []
    return [row for row in candidates if row.get("qualifies") is True]
