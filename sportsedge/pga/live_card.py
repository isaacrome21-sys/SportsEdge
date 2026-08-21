from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from .live_model import TruthGateResult, evaluate_live_truth_gate
from .market_pricing import MarketPrice, price_selection


@dataclass(frozen=True)
class CandidateMarket:
    market: str
    selection: str
    offered_american: float
    model_probability: float
    market_probability: float
    min_edge: float
    min_ev: float


@dataclass(frozen=True)
class LiveCardDecision:
    price: MarketPrice
    gate: TruthGateResult

    @property
    def status(self) -> str:
        return "OFFICIAL" if self.gate.passed else "NO_BET"


def evaluate_live_card(
    candidates: Iterable[CandidateMarket],
    *,
    leaderboard_timestamp: datetime | None,
    tee_time_timestamp: datetime | None,
    weather_timestamp: datetime | None,
    market_timestamp: datetime | None,
    has_shot_level_data: bool,
    wd_status_verified: bool,
    market_rules_verified: bool,
    now: datetime | None = None,
) -> tuple[LiveCardDecision, ...]:
    """Price and Truth-Gate normalized live PGA market candidates."""
    decisions: list[LiveCardDecision] = []
    for candidate in candidates:
        price = price_selection(
            market=candidate.market,
            selection=candidate.selection,
            offered_american=candidate.offered_american,
            model_probability=candidate.model_probability,
            market_probability=candidate.market_probability,
        )
        gate = evaluate_live_truth_gate(
            leaderboard_timestamp=leaderboard_timestamp,
            tee_time_timestamp=tee_time_timestamp,
            weather_timestamp=weather_timestamp,
            market_timestamp=market_timestamp,
            has_shot_level_data=has_shot_level_data,
            wd_status_verified=wd_status_verified,
            market_rules_verified=market_rules_verified,
            edge=price.edge,
            expected_value=price.expected_value,
            min_edge=candidate.min_edge,
            min_ev=candidate.min_ev,
            now=now,
        )
        decisions.append(LiveCardDecision(price=price, gate=gate))
    return tuple(decisions)
