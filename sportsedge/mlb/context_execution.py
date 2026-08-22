"""Projection context and execution controls for MLB betting decisions.

Sources of inspiration are public methodologies from THE BAT/THE BAT X,
Stuff+/Pitching+, park-specific weather research, UmpScorecards, and
professional market/execution practice. This module does not encode anyone's
proprietary formula and does not create promotion evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class PitchQualityContext:
    stuff_plus: float | None = None
    location_plus: float | None = None
    pitching_plus: float | None = None

    def k_multiplier(self) -> float:
        vals = [v for v in (self.stuff_plus, self.location_plus, self.pitching_plus) if v is not None]
        if not vals:
            return 1.0
        # Small bounded overlay only; downstream calibration owns the final weight.
        avg = sum(vals) / len(vals)
        return max(0.92, min(1.08, 1.0 + (avg - 100.0) / 500.0))


@dataclass(frozen=True)
class ParkWeatherContext:
    park_run_factor: float
    park_hr_factor: float
    weather_run_delta: float = 0.0
    weather_hr_delta: float = 0.0
    wind_out_mph: float = 0.0
    temperature_f: float | None = None
    dewpoint_f: float | None = None

    def run_multiplier(self) -> float:
        return max(0.70, min(1.35, self.park_run_factor * (1.0 + self.weather_run_delta)))

    def hr_multiplier(self) -> float:
        return max(0.60, min(1.60, self.park_hr_factor * (1.0 + self.weather_hr_delta)))


@dataclass(frozen=True)
class UmpireContext:
    accuracy_above_expected: float | None = None
    consistency: float | None = None
    total_run_impact: float | None = None
    called_strike_bias: float | None = None

    def run_multiplier(self) -> float:
        # Treat umpire as a modest context overlay; never let a noisy ump signal dominate.
        if self.total_run_impact is None:
            return 1.0
        return max(0.96, min(1.04, 1.0 + self.total_run_impact / 100.0))

    def k_multiplier(self) -> float:
        if self.called_strike_bias is None:
            return 1.0
        return max(0.96, min(1.04, 1.0 + self.called_strike_bias / 100.0))


@dataclass(frozen=True)
class ExecutionQuote:
    sportsbook: str
    american_odds: int
    max_stake: float | None = None
    available: bool = True
    captured_at_utc: str | None = None


def american_profit_per_unit(american: int) -> float:
    if american == 0:
        raise ValueError("American odds cannot be zero")
    return american / 100.0 if american > 0 else 100.0 / (-american)


def expected_value(probability: float, american_odds: int) -> float:
    if not 0.0 < probability < 1.0:
        raise ValueError("probability must be in (0,1)")
    b = american_profit_per_unit(american_odds)
    return probability * b - (1.0 - probability)


def best_executable_quote(probability: float, quotes: tuple[ExecutionQuote, ...], *, min_stake: float = 1.0) -> ExecutionQuote | None:
    """Choose the best positive-EV quote that is actually executable.

    Price without availability/limit is not treated as a tradable opportunity.
    """
    eligible = []
    for q in quotes:
        if not q.available:
            continue
        if q.max_stake is not None and (not isfinite(q.max_stake) or q.max_stake < min_stake):
            continue
        ev = expected_value(probability, q.american_odds)
        if ev > 0:
            eligible.append((ev, q))
    if not eligible:
        return None
    return max(eligible, key=lambda x: x[0])[1]


def execution_gate(probability: float, quote: ExecutionQuote | None, *, min_ev: float = 0.02, min_stake: float = 10.0) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    if quote is None:
        return False, ("NO_EXECUTABLE_QUOTE",)
    if not quote.available:
        reasons.append("QUOTE_UNAVAILABLE")
    if quote.max_stake is not None and quote.max_stake < min_stake:
        reasons.append("LIMIT_TOO_LOW")
    if expected_value(probability, quote.american_odds) < min_ev:
        reasons.append("EXECUTABLE_EV_TOO_SMALL")
    return not reasons, tuple(reasons)


def promotion_evidence() -> bool:
    return False
