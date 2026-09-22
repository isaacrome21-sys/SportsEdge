"""Transparent bettor-facing pricing for NFL RUN IT.

This is a presentation layer inspired by the disclosed MySpariEdge board pattern:
model estimate, fair price, sportsbook comparison, edge/EV, and a sortable score.
It does not reproduce or claim MySpariEdge's proprietary score formula or weights.
The score is not a calibrated win probability and grants no Model_P/Truth-Gate authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from sportsedge.truth_gate import american_to_decimal


SCORE_LABEL = "SPORTSEDGE_TRANSPARENT_EV_SCORE_V1"


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


def transparent_score(ev_per_dollar: float) -> int:
    """Map price economics to a bounded display score; 50 means zero EV.

    This intentionally mirrors SportsEdge's already-merged transparent NHL scoring
    convention so scores are comparable in meaning across RUN IT surfaces. It is
    a presentation transform only, never a win probability or performance claim.
    """
    if not isfinite(ev_per_dollar):
        raise NflRunItScoreError("ev_per_dollar must be finite")
    return int(round(max(0.0, min(100.0, 50.0 + 200.0 * ev_per_dollar))))


def price_run_it_pick(
    *,
    estimate_p: float,
    push_p: float,
    price_american: int,
    market_no_vig_p: float,
) -> NflRunItPrice:
    for name, value in (
        ("estimate_p", estimate_p),
        ("push_p", push_p),
        ("market_no_vig_p", market_no_vig_p),
    ):
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
    return NflRunItPrice(
        estimate_p=estimate_p,
        push_p=push_p,
        loss_p=loss_p,
        fair_probability=fair_probability,
        fair_american=fair_american,
        market_no_vig_p=market_no_vig_p,
        edge_probability_points=edge,
        ev_per_dollar=ev,
        score_0_100=transparent_score(ev),
    )
