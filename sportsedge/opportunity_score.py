"""Native SportsEdge opportunity scoring.

The score ranks the quality of a priced opportunity. It is deliberately NOT a
win probability. Model probability remains a separate field.
"""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite
from typing import Any

@dataclass(frozen=True)
class OpportunityScore:
    model_p: float
    fair_american_odds: int | None
    book_american_odds: int
    ev_per_dollar: float
    edge_probability_points: float
    score: int
    stars: float

def american_implied_probability(odds: Any) -> float:
    value=float(odds)
    if not isfinite(value) or value == 0: raise ValueError("american odds must be finite and non-zero")
    return 100/(value+100) if value>0 else (-value)/((-value)+100)

def probability_to_american(p: float) -> int | None:
    p=float(p)
    if not isfinite(p) or not 0<=p<=1: raise ValueError("probability must be between zero and one inclusive")
    # American odds have no finite representation at probability endpoints.
    # Keep the genuine model probability unchanged and expose fair odds as
    # unavailable rather than clipping a deterministic result to a fake price.
    if p == 0 or p == 1:
        return None
    raw=-100*p/(1-p) if p>=.5 else 100*(1-p)/p
    return int(round(raw))

def expected_value_per_dollar(model_p: float, american_odds: Any) -> float:
    p=float(model_p); odds=float(american_odds)
    if not isfinite(p) or not 0<=p<=1: raise ValueError("model_p must be between zero and one inclusive")
    if not isfinite(odds) or odds==0: raise ValueError("american odds must be finite and non-zero")
    profit=odds/100 if odds>0 else 100/(-odds)
    return p*profit-(1-p)

def opportunity_score(*, model_p: float, book_american_odds: Any, reliability: float=1.0,
                      data_quality: float=1.0, freshness: float=1.0,
                      simulation_stability: float=1.0) -> OpportunityScore:
    p=float(model_p); book=int(round(float(book_american_odds)))
    market_p=american_implied_probability(book)
    ev=expected_value_per_dollar(p, book)
    edge_pp=100*(p-market_p)
    qs=[float(reliability),float(data_quality),float(freshness),float(simulation_stability)]
    if any(not isfinite(q) or q<0 or q>1 for q in qs): raise ValueError("quality inputs must be between zero and one")
    quality=sum(qs)/len(qs)
    # 50 is neutral; evidence quality scales the strength of the priced signal.
    raw_signal=ev*180 + edge_pp*1.8
    score=int(round(max(0,min(100,50+quality*raw_signal))))
    stars=5.0 if score>=90 else 4.5 if score>=82 else 4.0 if score>=74 else 3.5 if score>=66 else 3.0 if score>=58 else 2.5 if score>=50 else 2.0 if score>=42 else 1.5 if score>=34 else 1.0
    return OpportunityScore(p,probability_to_american(p),book,ev,edge_pp,score,stars)
