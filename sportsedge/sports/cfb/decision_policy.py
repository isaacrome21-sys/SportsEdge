"""CFB candidate selection and live decision policy.

Historical candidate formation cannot require prior certification; live execution must.
This breaks circular promotion while preserving the frozen live edge semantics.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


class CFBDecisionPolicyError(ValueError):
    pass


@dataclass(frozen=True)
class CFBPolicyDecision:
    status: str
    reason: str


def _edge(value: float) -> float:
    out = float(value)
    if not isfinite(out):
        raise CFBDecisionPolicyError("EDGE_NONFINITE")
    return out


def _ev(value: float) -> float:
    out = float(value)
    if not isfinite(out):
        raise CFBDecisionPolicyError("EV_NONFINITE")
    return out


def historical_candidate_policy(
    *,
    edge: float,
    ev_per_dollar: float,
    quote_fresh: bool,
    two_sided: bool,
    data_quality_ok: bool,
    pit_ok: bool,
    coverage_ok: bool,
    policy_sha_ok: bool,
    min_edge: float = 0.03,
) -> CFBPolicyDecision:
    """Frozen selection policy used to construct the historical promotion sample."""

    flags = (quote_fresh, two_sided, data_quality_ok, pit_ok, coverage_ok, policy_sha_ok)
    if any(type(x) is not bool for x in flags):
        raise CFBDecisionPolicyError("POLICY_FLAGS_BOOL_REQUIRED")
    e = _edge(edge)
    ev = _ev(ev_per_dollar)
    floor = _edge(min_edge)
    if floor <= 0.0:
        raise CFBDecisionPolicyError("MIN_EDGE_MUST_BE_POSITIVE")
    if not data_quality_ok or not pit_ok or not coverage_ok or not policy_sha_ok:
        return CFBPolicyDecision("BLOCKED", "HISTORICAL_DATA_OR_POLICY_GATE")
    if not quote_fresh or not two_sided:
        return CFBPolicyDecision("BLOCKED", "HISTORICAL_PRICE_GATE")
    if e < floor or ev <= 0.0:
        return CFBPolicyDecision("NO_BET", "EDGE_OR_EV_BELOW_POLICY")
    return CFBPolicyDecision("SHADOW_QUALIFIED", "HISTORICAL_CANDIDATE_QUALIFIED")


def live_candidate_decision(
    *,
    edge: float,
    ev_per_dollar: float,
    quote_fresh: bool,
    two_sided: bool,
    exposure_ok: bool,
    data_quality_ok: bool,
    coverage_ok: bool,
    override_log_complete: bool,
    policy_sha_ok: bool,
    historical_status: str,
    min_edge: float = 0.03,
) -> CFBPolicyDecision:
    """Live policy: historical certification is an additional hard prerequisite."""

    flags = (
        quote_fresh, two_sided, exposure_ok, data_quality_ok, coverage_ok,
        override_log_complete, policy_sha_ok,
    )
    if any(type(x) is not bool for x in flags):
        raise CFBDecisionPolicyError("POLICY_FLAGS_BOOL_REQUIRED")
    e = _edge(edge)
    ev = _ev(ev_per_dollar)
    floor = _edge(min_edge)
    if str(historical_status).upper() != "OFFICIAL":
        return CFBPolicyDecision("BLOCKED", "HISTORICAL_MARKET_NOT_OFFICIAL")
    if not data_quality_ok or not coverage_ok or not override_log_complete or not policy_sha_ok:
        return CFBPolicyDecision("BLOCKED", "LIVE_DATA_OR_POLICY_GATE")
    if not quote_fresh or not two_sided or not exposure_ok:
        return CFBPolicyDecision("BLOCKED", "LIVE_EXECUTION_GATE")
    if e < floor or ev <= 0.0:
        return CFBPolicyDecision("NO_BET", "EDGE_OR_EV_BELOW_POLICY")
    return CFBPolicyDecision("OFFICIAL_BET", "LIVE_CANDIDATE_QUALIFIED")
