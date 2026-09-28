"""Transparent MySpari-style presentation metrics for SportsEdge CFB.

Uses SportsEdge probabilities; no proprietary MySpariEdge weights are copied.
Confidence is a ranking/quality score, not a win probability.
"""
from __future__ import annotations
from math import isfinite

class CFBScorecardError(ValueError):
    pass

def probability_to_american(probability: float) -> int:
    p=float(probability)
    if not isfinite(p) or not 0.0 < p < 1.0:
        raise CFBScorecardError("CFB_FAIR_PROBABILITY_INVALID")
    return int(round(-100.0*p/(1.0-p))) if p >= .5 else int(round(100.0*(1.0-p)/p))

def confidence_score(*, model_p: float, fair_market_p: float, ev_per_dollar: float,
                     push_p: float=0.0, n_paths: int=20000,
                     quote_age_seconds: float=0.0, quote_ttl_seconds: float=180.0) -> float:
    """Qualification-only Score B.

    Market edge, EV, price attractiveness, and the magnitude of Model_P never
    contribute points. The market/EV arguments remain only for API compatibility
    and finite-input hygiene.
    """
    p=float(model_p); market=float(fair_market_p); ev=float(ev_per_dollar); push=float(push_p)
    if not all(isfinite(x) for x in (p,market,ev,push)):
        raise CFBScorecardError("CFB_SCORECARD_NONFINITE")
    if not (0<=p<=1 and 0<=market<=1 and 0<=push<1):
        raise CFBScorecardError("CFB_SCORECARD_PROBABILITY_INVALID")
    if isinstance(n_paths,bool) or int(n_paths)<=0:
        raise CFBScorecardError("CFB_SCORECARD_PATHS_INVALID")
    ttl=float(quote_ttl_seconds); age=max(0.0,float(quote_age_seconds))
    if not isfinite(ttl) or ttl<=0:
        raise CFBScorecardError("CFB_SCORECARD_TTL_INVALID")

    # Locked Score rule B: points come only from qualification checks.
    path_points=40.0*min(1.0,int(n_paths)/20000.0)
    freshness_points=40.0*max(0.0,1.0-age/ttl)
    push_points=20.0*max(0.0,1.0-push/0.30)
    return round(max(0.0,min(100.0,path_points+freshness_points+push_points)),1)

def build_scorecard(*, model_p: float, fair_market_p: float, american_odds: float,
                    edge: float, ev_per_dollar: float, push_p: float=0.0,
                    n_paths: int=20000, quote_age_seconds: float=0.0,
                    quote_ttl_seconds: float=180.0) -> dict[str,float|int|str]:
    non_push=1.0-float(push_p)
    if non_push<=0:
        raise CFBScorecardError("CFB_SCORECARD_SETTLED_SPACE_EMPTY")
    settled=float(model_p)/non_push
    # Finite Monte Carlo samples can legitimately produce exact 0/1 outcomes.
    # Keep the scorecard total and explicit instead of crashing RUN IT.
    fair_odds: int | str = (
        probability_to_american(settled)
        if 0.0 < settled < 1.0
        else ("OFF_BOARD_-INF" if settled >= 1.0 else "OFF_BOARD_+INF")
    )
    return {
        "model_pct":round(settled*100.0,1),
        "fair_odds":fair_odds,
        "book_odds":int(round(float(american_odds))),
        "market_no_vig_pct":round(float(fair_market_p)*100.0,1),
        "edge_pct":round(float(edge)*100.0,1),
        "ev_pct":round(float(ev_per_dollar)*100.0,1),
        "confidence":confidence_score(model_p=model_p,fair_market_p=fair_market_p,
            ev_per_dollar=ev_per_dollar,push_p=push_p,n_paths=n_paths,
            quote_age_seconds=quote_age_seconds,quote_ttl_seconds=quote_ttl_seconds),
        "confidence_semantics":"QUALITY_SCORE_NOT_WIN_PROBABILITY",
    }
