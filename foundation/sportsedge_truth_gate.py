#!/usr/bin/env python3
"""Pure deterministic SportsEdge bet decision gate."""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Decision:
    model_status: str
    bet_status: str
    reason: str
    ev_pct: Optional[float] = None
    stake_units: Optional[float] = None


def _american_to_decimal(odds: float) -> float:
    if isinstance(odds, bool) or not isinstance(odds, (int, float)) or not (odds <= -100 or odds >= 100):
        raise ValueError(f"invalid American odds: {odds} (must be <=-100 or >=100)")
    return 1.0 + (100.0 / abs(odds) if odds < 0 else odds / 100.0)


def truth_gate(model_p: float, american_odds: float, *, binding_ok: bool,
               binding_reason: str, deployment_eligible: bool,
               freshness_ok: bool, freshness_reason: str,
               min_edge_pct: float = 3.0, kelly_fraction: float = 0.25) -> Decision:
    if isinstance(model_p, bool) or not isinstance(model_p, (int, float)) or not 0.0 <= float(model_p) <= 1.0:
        return Decision("INVALID", "BLOCKED", f"Model_P out of range: {model_p}")
    if deployment_eligible is not True:
        return Decision("NOT_DEPLOYED", "BLOCKED", "market not deployment-eligible")
    if not binding_ok:
        return Decision("VALID", "BLOCKED", f"candidate binding failed: {binding_reason}")
    if not freshness_ok:
        return Decision("VALID", "BLOCKED", f"price freshness failed: {freshness_reason}")
    try:
        dec = _american_to_decimal(american_odds)
    except ValueError as exc:
        return Decision("VALID", "BLOCKED", str(exc))
    ev_pct = 100.0 * (float(model_p) * dec - 1.0)
    b = dec - 1.0
    q = 1.0 - float(model_p)
    kelly = max(0.0, (float(model_p) * b - q) / b) if b > 0 else 0.0
    stake = round(kelly * kelly_fraction, 4)
    if ev_pct < min_edge_pct:
        return Decision("VALID", "PASS", f"edge {ev_pct:.2f}% below {min_edge_pct}% threshold", ev_pct, 0.0)
    return Decision("VALID", "OFFICIAL_BET", "clears truth gate", ev_pct, stake)
