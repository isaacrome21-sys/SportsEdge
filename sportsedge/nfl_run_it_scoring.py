"""Transparent bettor-facing pricing for NFL RUN IT.

The user-supplied MySpariEdge NFL Props Edge / Prop Picks / Touchdown Picks /
Game Picks materials motivate the bettor-facing separation of model estimate,
fair price, market comparison and a sortable 0-100 presentation. SportsEdge does
not copy MySpariEdge's hidden formula or weights.

Locked Score rule B: EV and edge are economics used to qualify/rank candidates;
they never feed the 0-100 Score. Score is built only from explicit model/role
qualification flags supplied upstream. It is not a calibrated win probability.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Mapping

from sportsedge.truth_gate import american_to_decimal

SCORE_LABEL = "SPORTSEDGE_QUALIFICATION_ROLE_SCORE_V1"
QUALIFICATION_FLAGS = (
    "model_ready", "pit_safe", "role_stable", "usage_supported",
    "matchup_supported", "injury_context_ready", "shared_simulation_ready",
    "market_binding_ready",
)

class NflRunItScoreError(ValueError):
    pass

@dataclass(frozen=True)
class NflRunItPrice:
    estimate_p: float
    push_p: float
    loss_p: float
    fair_probability: float
    fair_american: int
    market_no_vig_p: float
    edge_probability_points: float
    ev_per_dollar: float
    score_0_100: int
    score_label: str = SCORE_LABEL

def american_from_probability(probability: float) -> int:
    if not isfinite(probability) or not 0.0 < probability < 1.0:
        raise NflRunItScoreError("probability must be finite and in (0,1)")
    if probability >= 0.5:
        return int(round(-100.0 * probability / (1.0 - probability)))
    return int(round(100.0 * (1.0 - probability) / probability))

def qualification_role_score(flags: Mapping[str, bool]) -> int:
    """Return a 0-100 display score from qualification/role flags only."""
    if not isinstance(flags, Mapping):
        raise NflRunItScoreError("qualification flags must be a mapping")
    if set(flags) != set(QUALIFICATION_FLAGS):
        raise NflRunItScoreError("qualification flags must match frozen schema")
    if any(type(flags[name]) is not bool for name in QUALIFICATION_FLAGS):
        raise NflRunItScoreError("qualification flags must be boolean")
    return int(round(100.0 * sum(int(flags[n]) for n in QUALIFICATION_FLAGS) / len(QUALIFICATION_FLAGS)))

def price_run_it_pick(*, estimate_p: float, push_p: float, price_american: int,
                      market_no_vig_p: float,
                      qualification_flags: Mapping[str, bool] | None = None) -> NflRunItPrice:
    for name, value in (("estimate_p", estimate_p), ("push_p", push_p), ("market_no_vig_p", market_no_vig_p)):
        if not isfinite(value):
            raise NflRunItScoreError(f"{name} must be finite")
    if estimate_p < 0.0 or push_p < 0.0 or estimate_p + push_p > 1.0 + 1e-12:
        raise NflRunItScoreError("invalid win/push mass")
    if not 0.0 < market_no_vig_p < 1.0:
        raise NflRunItScoreError("market_no_vig_p must be in (0,1)")
    if -100 < int(price_american) < 100:
        raise NflRunItScoreError("American odds must be <= -100 or >= +100")
    loss_p = max(0.0, 1.0 - estimate_p - push_p)
    decisive = estimate_p + loss_p
    if decisive <= 0.0:
        raise NflRunItScoreError("cannot price an all-push outcome")
    fair_probability = estimate_p / decisive
    fair_american = american_from_probability(fair_probability)
    edge = fair_probability - market_no_vig_p
    decimal = american_to_decimal(int(price_american))
    ev = estimate_p * (decimal - 1.0) - loss_p
    # Legacy callers without role flags get a fail-closed zero score, never an
    # EV-derived substitute. Follow-up RUN IT wiring supplies real flags.
    flags = qualification_flags if qualification_flags is not None else {n: False for n in QUALIFICATION_FLAGS}
    score = qualification_role_score(flags)
    return NflRunItPrice(estimate_p, push_p, loss_p, fair_probability, fair_american,
                         market_no_vig_p, edge, ev, score)
