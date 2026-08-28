from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Iterable, Mapping

from .live_model import TournamentSimulationResult, TruthGateResult, evaluate_live_truth_gate
from .market_pricing import DeadHeatMarketPrice, price_dead_heat_position


_SUPPORTED_POSITION_MARKETS = {
    "OUTRIGHT": ("win_prob", "win_prob"),
    "WINNER": ("win_prob", "win_prob"),
    "TOP_5": ("top5_prob", "top5_dead_heat_payout"),
    "TOP5": ("top5_prob", "top5_dead_heat_payout"),
    "TOP_10": ("top10_prob", "top10_dead_heat_payout"),
    "TOP10": ("top10_prob", "top10_dead_heat_payout"),
    "TOP_20": ("top20_prob", "top20_dead_heat_payout"),
    "TOP20": ("top20_prob", "top20_dead_heat_payout"),
}


@dataclass(frozen=True)
class CandidateMarket:
    """Normalized offered market; model probabilities are never accepted from the caller."""
    market: str
    selection: str
    offered_american: float
    market_probability: float
    min_edge: float
    min_ev: float
    bound: bool = False
    promoted: bool = False

    def __post_init__(self) -> None:
        if not str(self.market).strip() or not str(self.selection).strip():
            raise ValueError("PGA_CANDIDATE_IDENTITY_REQUIRED")
        market = str(self.market).strip().upper()
        if market not in _SUPPORTED_POSITION_MARKETS:
            raise ValueError(f"PGA_LIVE_MARKET_UNSUPPORTED:{market}")
        if any(type(value) is not bool for value in (self.bound, self.promoted)):
            raise ValueError("PGA_CANDIDATE_BOOLEAN_INVALID")
        for label, value in (
            ("market_probability", self.market_probability),
            ("min_edge", self.min_edge),
            ("min_ev", self.min_ev),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)):
                raise ValueError(f"PGA_CANDIDATE_{label.upper()}_INVALID")
        if not 0.0 < self.market_probability < 1.0:
            raise ValueError("PGA_CANDIDATE_MARKET_PROBABILITY_INVALID")
        if self.min_edge <= 0 or self.min_ev <= 0:
            raise ValueError("PGA_CANDIDATE_THRESHOLDS_INVALID")


@dataclass(frozen=True)
class LiveCardDecision:
    price: DeadHeatMarketPrice
    gate: TruthGateResult
    edge: float
    status: str
    block_reason: str | None = None


def _simulation_price_input(
    candidate: CandidateMarket,
    simulation: Mapping[str, TournamentSimulationResult],
) -> tuple[float, float]:
    row = simulation.get(candidate.selection)
    if row is None:
        raise ValueError(f"PGA_SELECTION_NOT_IN_SIMULATION:{candidate.selection}")
    market = candidate.market.strip().upper()
    raw_attr, paid_attr = _SUPPORTED_POSITION_MARKETS[market]
    raw_probability = float(getattr(row, raw_attr))
    expected_paid_fraction = float(getattr(row, paid_attr))
    return raw_probability, expected_paid_fraction


def evaluate_live_card(
    candidates: Iterable[CandidateMarket],
    *,
    simulation: Mapping[str, TournamentSimulationResult],
    leaderboard_timestamp: datetime | None,
    tee_time_timestamp: datetime | None,
    weather_timestamp: datetime | None,
    market_timestamp: datetime | None,
    has_shot_level_data: bool,
    wd_status_verified: bool,
    market_rules_verified: bool,
    now: datetime | None = None,
) -> tuple[LiveCardDecision, ...]:
    """Price live PGA offers from simulator readouts and apply fail-closed gates.

    The caller supplies the sportsbook price and no-vig market probability, but
    cannot inject a model probability. Outright/top-K settlement uses expected
    paid fraction, so dead heats reduce EV instead of being treated as full wins.
    Promotion remains explicit and separate from code availability.
    """
    decisions: list[LiveCardDecision] = []
    for candidate in candidates:
        raw_probability, expected_paid_fraction = _simulation_price_input(candidate, simulation)
        price = price_dead_heat_position(
            market=candidate.market.strip().upper(),
            selection=candidate.selection,
            offered_american=candidate.offered_american,
            raw_finish_probability=raw_probability,
            expected_paid_fraction=expected_paid_fraction,
        )
        # Compare the settlement-adjusted model share to the no-vig market share.
        # This is conservative for dead-heat markets because only paid probability
        # mass, not headline finish probability, is credited as model edge.
        edge = expected_paid_fraction - float(candidate.market_probability)
        gate = evaluate_live_truth_gate(
            leaderboard_timestamp=leaderboard_timestamp,
            tee_time_timestamp=tee_time_timestamp,
            weather_timestamp=weather_timestamp,
            market_timestamp=market_timestamp,
            has_shot_level_data=has_shot_level_data,
            wd_status_verified=wd_status_verified,
            market_rules_verified=market_rules_verified,
            edge=edge,
            expected_value=price.expected_value,
            min_edge=candidate.min_edge,
            min_ev=candidate.min_ev,
            now=now,
        )
        if not candidate.bound:
            status, reason = "BLOCKED", "MARKET_NOT_BOUND"
        elif not candidate.promoted:
            status, reason = "BLOCKED", "PGA_MARKET_NOT_PROMOTED"
        elif not gate.passed:
            status, reason = "PASS", "TRUTH_GATE_REJECTED"
        else:
            status, reason = "OFFICIAL_BET", None
        decisions.append(LiveCardDecision(price=price, gate=gate, edge=edge, status=status, block_reason=reason))
    return tuple(decisions)
