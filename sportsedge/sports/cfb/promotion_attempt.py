"""CFB promotion-attempt harness for the first real Week 1 evaluation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable

from sportsedge.core.promotion.football import FootballPromotionEvidence, evaluate_football_promotion, official_candidates


@dataclass(frozen=True)
class CFBPromotionAttempt:
    market: str
    as_of_date: str
    stage: str
    official_plays: tuple[dict, ...]
    zero_is_valid: bool


def run_cfb_promotion_attempt(
    *,
    market: str,
    evidence: FootballPromotionEvidence,
    candidates: Iterable[dict],
    as_of_date: str,
) -> CFBPromotionAttempt:
    market_name = str(market).strip().lower()
    if not market_name:
        raise ValueError("MARKET_MISSING")
    parsed = date.fromisoformat(str(as_of_date))
    stage = evaluate_football_promotion(evidence)
    official = tuple(official_candidates(list(candidates), stage))
    return CFBPromotionAttempt(
        market=market_name,
        as_of_date=parsed.isoformat(),
        stage=stage,
        official_plays=official,
        zero_is_valid=True,
    )
