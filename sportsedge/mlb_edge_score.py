"""Non-authoritative MLB edge/confidence presentation.

This layer intentionally consumes an estimate_p / Model_P value; it never creates
or modifies it. Social, capper, split, weather commentary, and other context are
display-only and cannot change the score. Governance/Truth Gate remains separate.
"""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping

from sports.common.ev_math import EVError, american_to_decimal as _american_to_decimal, devig as _devig


class MLBEdgeScoreError(ValueError):
    pass


MLB_EDGE_SCORE_PROVENANCE = "MODEL_P_EDGE_SCORE_V1"
AUTHORITY_FOOTER = "NOT Model_P / NOT Truth Gate / NOT OFFICIAL · estimate_p is not certified Model_P"


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


def ev_per_dollar(p: float, odds: int | float, *, push_p: float = 0.0) -> float:
    """Push-aware EV: pushes return stake, so only win and lose mass move the bankroll."""
    o=float(odds)
    win_p=float(p)
    push=float(push_p)
    if win_p < 0 or push < 0 or win_p + push > 1.0 + 1e-12:
        raise MLBEdgeScoreError("INVALID_WIN_PUSH_MASS")
    lose_p=max(0.0, 1.0 - win_p - push)
    profit = 100.0/(-o) if o < 0 else o/100.0
    return win_p*profit - lose_p


def binary_no_vig_probability(odds: int|float, opposite_odds: int|float) -> float:
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
    estimate_p: float | None
    market_p: float | None
    fair_odds: int | None
    edge: float | None
    ev_per_dollar: float | None
    reason_codes: tuple[str, ...]
    confidence_provenance: str = MLB_EDGE_SCORE_PROVENANCE
    authority_footer: str = AUTHORITY_FOOTER


def score_mlb_edge(
    *, model_p: float | None = None, estimate_p: float | None = None,
    american_odds: int | float | None,
    opposite_odds: int | float | None = None, n_way_market: bool = False,
    quote_age_seconds: float = 0.0, quote_ttl_seconds: float = 180.0,
    reliability: float = 1.0, inputs_complete: bool = True,
    model_available: bool = True, min_actionable_ev: float = 0.0,
    push_p: float = 0.0,
    context: Mapping[str, Any] | None = None,
) -> MLBScoredEdge:
    _ = context
    p_raw = estimate_p if estimate_p is not None else model_p
    if not model_available or p_raw is None:
        return MLBScoredEdge("NO_MODEL",0,None,None,None,None,None,None,("MODEL_UNAVAILABLE",))
    p=float(p_raw)
    if not 0 < p < 1:
        raise MLBEdgeScoreError("MODEL_P_OUT_OF_RANGE")
    if not inputs_complete:
        return MLBScoredEdge("BLOCKED",0,p,p,None,fair_american_odds(p),None,None,("REQUIRED_INPUT_MISSING",))
    if american_odds is None:
        return MLBScoredEdge("BLOCKED",0,p,p,None,fair_american_odds(p),None,None,("QUOTE_MISSING",))
    if quote_ttl_seconds <= 0 or quote_age_seconds < 0:
        raise MLBEdgeScoreError("INVALID_QUOTE_AGE_OR_TTL")
    if quote_age_seconds > quote_ttl_seconds:
        return MLBScoredEdge("BLOCKED",0,p,p,None,fair_american_odds(p),None,None,("STALE_QUOTE",))
    american_implied_probability(american_odds)
    if n_way_market:
        return MLBScoredEdge("BLOCKED",0,p,p,None,fair_american_odds(p),None,None,("N_WAY_DEVIG_UNFROZEN",))
    if opposite_odds is None:
        return MLBScoredEdge("BLOCKED",0,p,p,None,fair_american_odds(p),None,None,("OPPOSITE_QUOTE_UNAVAILABLE",))
    try:
        market_p=binary_no_vig_probability(american_odds, opposite_odds)
    except MLBEdgeScoreError as exc:
        if str(exc) != "DEVIG_METHOD_SENSITIVITY":
            raise
        return MLBScoredEdge("BLOCKED",0,p,p,None,fair_american_odds(p),None,None,("DEVIG_METHOD_SENSITIVITY",))
    reasons=["POWER_V1_NO_VIG","ESTIMATE_P_UNOFFICIAL"]
    edge=p-market_p
    ev=ev_per_dollar(p, american_odds, push_p=push_p)
    rel=float(reliability)
    if not isfinite(rel) or rel < 0.0 or rel > 1.0:
        raise MLBEdgeScoreError("MODEL_RELIABILITY_OUT_OF_RANGE")
    # A reported 0.0 reliability stays 0.0. It must not be quietly lifted by the
    # 0.70 floor that used to keep a zero-reliability card looking confident.
    freshness=max(0.0,min(1.0,1.0-quote_age_seconds/quote_ttl_seconds))
    edge_strength=max(0.0,min(1.0,edge/.08))
    ev_strength=max(0.0,min(1.0,ev/.15))
    strength=.55*ev_strength+.45*edge_strength
    if rel == 0.0:
        score=0
    else:
        score=round(100.0*strength*rel*(.85+.15*freshness))
        score=max(0,min(100,score))
    status="ACTIONABLE" if ev > min_actionable_ev and edge > 0 and rel > 0 else "PASS"
    return MLBScoredEdge(status,score,p,p,market_p,fair_american_odds(p),edge,ev,tuple(reasons))
