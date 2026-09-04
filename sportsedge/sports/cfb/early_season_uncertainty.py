"""Early-season uncertainty governance for SportsEdge CFB.

This layer is intentionally separate from raw Model_P. It does not rewrite the
joint model probability. Instead it widens decision uncertainty and can downgrade
marginal betting candidates to PASS when Weeks 0-2 depend on fragile personnel
assumptions (new QB, portal churn, OL turnover, coordinator/system changes, or
unsettled depth charts).

Rutgers-UMass and Georgia Tech-Colorado on 2026-09-03 are motivating postmortems,
not training labels and must never be backfit into pregame probabilities.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable, Mapping, Any

CFB_EARLY_SEASON_POLICY_VERSION = "CFB_EARLY_SEASON_UNCERTAINTY_V1"
EARLY_WEEKS = frozenset({0, 1, 2})


class CFBEarlySeasonPolicyError(ValueError):
    pass


@dataclass(frozen=True)
class CFBPersonnelUncertainty:
    new_starting_qb: bool = False
    qb_career_starts: int | None = None
    transfer_qb: bool = False
    returning_ol_starters: int | None = None
    portal_turnover_rate: float | None = None
    new_offensive_coordinator: bool = False
    new_head_coach: bool = False
    depth_chart_unsettled: bool = False


@dataclass(frozen=True)
class CFBEarlySeasonDecision:
    risk_score: float
    uncertainty_multiplier: float
    edge_haircut: float
    favorite_extra_haircut: float
    hard_pass: bool
    reasons: tuple[str, ...]


def _finite_unit(value: float | None, name: str) -> float | None:
    if value is None:
        return None
    out = float(value)
    if not isfinite(out) or out < 0.0 or out > 1.0:
        raise CFBEarlySeasonPolicyError(f"{name}_MUST_BE_0_TO_1")
    return out


def assess_early_season_uncertainty(
    *,
    week: int,
    personnel: CFBPersonnelUncertainty,
    is_favorite: bool,
    spread_abs: float | None = None,
) -> CFBEarlySeasonDecision:
    """Return a market-blind governance adjustment for Weeks 0-2.

    The returned edge haircuts are probability-point deductions applied only to
    the downstream decision edge, never to raw Model_P. uncertainty_multiplier
    is suitable for widening score/margin residual dispersion in a future model
    candidate, subject to separate validation before promotion.
    """
    if isinstance(week, bool) or int(week) < 0:
        raise CFBEarlySeasonPolicyError("WEEK_INVALID")
    if int(week) not in EARLY_WEEKS:
        return CFBEarlySeasonDecision(0.0, 1.0, 0.0, 0.0, False, ())

    reasons: list[str] = []
    risk = 0.0

    if personnel.new_starting_qb:
        risk += 0.24
        reasons.append("NEW_STARTING_QB")
    if personnel.transfer_qb:
        risk += 0.08
        reasons.append("TRANSFER_QB")
    if personnel.qb_career_starts is not None:
        starts = int(personnel.qb_career_starts)
        if starts < 0:
            raise CFBEarlySeasonPolicyError("QB_CAREER_STARTS_NEGATIVE")
        if starts <= 2:
            risk += 0.16
            reasons.append("QB_0_TO_2_CAREER_STARTS")
        elif starts <= 6:
            risk += 0.08
            reasons.append("QB_3_TO_6_CAREER_STARTS")

    if personnel.returning_ol_starters is not None:
        ol = int(personnel.returning_ol_starters)
        if ol < 0 or ol > 5:
            raise CFBEarlySeasonPolicyError("RETURNING_OL_STARTERS_MUST_BE_0_TO_5")
        if ol <= 2:
            risk += 0.18
            reasons.append("LOW_OL_CONTINUITY")
        elif ol == 3:
            risk += 0.08
            reasons.append("MEDIUM_OL_CONTINUITY")

    portal = _finite_unit(personnel.portal_turnover_rate, "PORTAL_TURNOVER_RATE")
    if portal is not None:
        if portal >= 0.40:
            risk += 0.18
            reasons.append("HEAVY_PORTAL_TURNOVER")
        elif portal >= 0.25:
            risk += 0.09
            reasons.append("MODERATE_PORTAL_TURNOVER")

    if personnel.new_offensive_coordinator:
        risk += 0.10
        reasons.append("NEW_OFFENSIVE_COORDINATOR")
    if personnel.new_head_coach:
        risk += 0.10
        reasons.append("NEW_HEAD_COACH")
    if personnel.depth_chart_unsettled:
        risk += 0.14
        reasons.append("DEPTH_CHART_UNSETTLED")

    risk = min(1.0, risk)
    uncertainty_multiplier = 1.0 + 0.45 * risk
    edge_haircut = 0.030 * risk

    favorite_extra = 0.0
    spread = abs(float(spread_abs)) if spread_abs is not None else 0.0
    if is_favorite:
        favorite_extra += 0.008 * risk
        if spread >= 14.0:
            favorite_extra += 0.010 * risk
            reasons.append("LARGE_FAVORITE_UNCERTAINTY")
        if spread >= 24.0:
            favorite_extra += 0.012 * risk
            reasons.append("VERY_LARGE_FAVORITE_UNCERTAINTY")

    # Fail closed only when uncertainty is extreme and the candidate is a
    # favorite whose thesis is especially sensitive to fragile assumptions.
    hard_pass = bool(is_favorite and risk >= 0.72)
    if hard_pass:
        reasons.append("EARLY_SEASON_FAVORITE_HARD_PASS")

    return CFBEarlySeasonDecision(
        risk_score=round(risk, 6),
        uncertainty_multiplier=round(uncertainty_multiplier, 6),
        edge_haircut=round(edge_haircut, 6),
        favorite_extra_haircut=round(favorite_extra, 6),
        hard_pass=hard_pass,
        reasons=tuple(reasons),
    )


def adjusted_decision_edge(raw_edge: float, decision: CFBEarlySeasonDecision) -> float:
    """Haircut a downstream edge without altering raw Model_P."""
    edge = float(raw_edge)
    if not isfinite(edge):
        raise CFBEarlySeasonPolicyError("RAW_EDGE_NONFINITE")
    if decision.hard_pass:
        return min(edge, 0.0)
    return edge - decision.edge_haircut - decision.favorite_extra_haircut
