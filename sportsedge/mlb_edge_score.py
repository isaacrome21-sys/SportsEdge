"""Non-authoritative MLB edge/confidence presentation.

This layer intentionally consumes Model_P; it never creates or modifies it. Social,
capper, split, weather commentary, and other context are display-only and cannot
change the score. Governance/Truth Gate remains a separate certification layer.
"""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping

from sports.common.ev_math import EVError, american_to_decimal as _american_to_decimal, devig as _devig


class MLBEdgeScoreError(ValueError):
    pass


def american_implied_probability(odds: int | float) -> float:
    o=float(odds)
    if not isfinite(o) or o == 0 or -100 < o < 100:
        raise MLBEdgeScoreError("INVALID_AMERICAN_ODDS")
    return (-o)/((-o)+100.0) if o < 0 else 100.0/(o+100.0)


def fair_american_odds(p: float) -> int:
    p=float(p)
    if not 0 < p < 1:
        raise MLBEdgeScoreError("MODEL_P_OUT_OF_RANGE")
    raw = -100*p/(1-p) if p >= .5 else 100*(1-p)/p
    return int(round(raw))


def ev_per_dollar(p: float, odds: int | float) -> float:
    o=float(odds)
    profit = 100.0/(-o) if o < 0 else o/100.0
    return p*profit-(1-p)


def binary_no_vig_probability(odds: int|float, opposite_odds: int|float) -> float:
    """POWER_V1 two-sided no-vig probability for ``odds`` via the shared ev_math.devig.

    Above +400 the shared sensitivity guard compares POWER/MULTIPLICATIVE/SHIN and
    raises DEVIG_METHOD_SENSITIVITY when they disagree by more than 1pp. There is no
    minimum-across-methods rule: a sensitive market fails closed.
    """
    american_implied_probability(odds)
    american_implied_probability(opposite_odds)
    try:
        fair=_devig([_american_to_decimal(odds), _american_to_decimal(opposite_odds)],
                    trigger_american=400, max_spread_pp=1.0)
    except EVError as exc:
        raise MLBEdgeScoreError(exc.code) from exc
    return fair[0]


@dataclass(frozen=True)
class MLBScoredEdge:
    status: str
    confidence_score: int
    model_p: float | None
    market_p: float | None
    fair_odds: int | None
    edge: float | None
    ev_per_dollar: float | None
    reason_codes: tuple[str, ...]


def score_mlb_edge(
    *, model_p: float | None, american_odds: int | float | None,
    opposite_odds: int | float | None = None, n_way_market: bool = False,
    quote_age_seconds: float = 0.0, quote_ttl_seconds: float = 180.0,
    reliability: float = 1.0, inputs_complete: bool = True,
    model_available: bool = True, min_actionable_ev: float = 0.0,
    context: Mapping[str, Any] | None = None,
) -> MLBScoredEdge:
    # context is accepted for presentation plumbing only. Never use it below.
    _ = context
    if not model_available or model_p is None:
        return MLBScoredEdge("NO_MODEL",0,None,None,None,None,None,("MODEL_UNAVAILABLE",))
    p=float(model_p)
    if not 0 < p < 1:
        raise MLBEdgeScoreError("MODEL_P_OUT_OF_RANGE")
    if not inputs_complete:
        return MLBScoredEdge("BLOCKED",0,p,None,fair_american_odds(p),None,None,("REQUIRED_INPUT_MISSING",))
    if american_odds is None:
        return MLBScoredEdge("BLOCKED",0,p,None,fair_american_odds(p),None,None,("QUOTE_MISSING",))
    if quote_ttl_seconds <= 0 or quote_age_seconds < 0:
        raise MLBEdgeScoreError("INVALID_QUOTE_AGE_OR_TTL")
    if quote_age_seconds > quote_ttl_seconds:
        return MLBScoredEdge("BLOCKED",0,p,None,fair_american_odds(p),None,None,("STALE_QUOTE",))
    american_implied_probability(american_odds)
    if n_way_market:
        # N-way markets (e.g. FIRST_HOME_RUN) need their own frozen N-way/no-HR
        # settlement and devig methodology; two-sided POWER_V1 does not apply and
        # raw vig-inclusive implied probability is never a fair baseline.
        return MLBScoredEdge("BLOCKED",0,p,None,fair_american_odds(p),None,None,("N_WAY_DEVIG_UNFROZEN",))
    if opposite_odds is None:
        # One-sided quotes are refused: no paired same-book/same-line price, no score.
        return MLBScoredEdge("BLOCKED",0,p,None,fair_american_odds(p),None,None,("OPPOSITE_QUOTE_UNAVAILABLE",))
    try:
        market_p=binary_no_vig_probability(american_odds, opposite_odds)
    except MLBEdgeScoreError as exc:
        if str(exc) != "DEVIG_METHOD_SENSITIVITY":
            raise
        return MLBScoredEdge("BLOCKED",0,p,None,fair_american_odds(p),None,None,("DEVIG_METHOD_SENSITIVITY",))
    reasons=["POWER_V1_NO_VIG"]
    edge=p-market_p
    ev=ev_per_dollar(p, american_odds)
    rel=max(0.0,min(1.0,float(reliability)))
    freshness=max(0.0,min(1.0,1.0-quote_age_seconds/quote_ttl_seconds))
    # Score is evidence strength, not win probability: EV/edge drive upside while
    # reliability and quote freshness prevent unsupported 90+ grades.
    edge_strength=max(0.0,min(1.0,edge/.08))
    ev_strength=max(0.0,min(1.0,ev/.15))
    strength=.55*ev_strength+.45*edge_strength
    score=round(100.0*strength*(.70+.30*rel)*(.85+.15*freshness))
    score=max(0,min(100,score))
    status="ACTIONABLE" if ev > min_actionable_ev and edge > 0 else "PASS"
    return MLBScoredEdge(status,score,p,market_p,fair_american_odds(p),edge,ev,tuple(reasons))
