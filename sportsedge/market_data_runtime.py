"""Fail-closed runtime authority for market-data backed SportsEdge surfaces."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .market_data_contract import MarketQuote, PublicBettingSplit


@dataclass(frozen=True)
class MarketRuntimeDecision:
    status: str
    card_stage: str
    stake_units: float
    model_p_authority: bool
    staking_authority: bool
    live_engine_status: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "card_stage": self.card_stage,
            "stake_units": self.stake_units,
            "model_p_authority": self.model_p_authority,
            "staking_authority": self.staking_authority,
            "live_engine_status": self.live_engine_status,
            "reason": self.reason,
            "official_authority": False,
        }


def decide_market_runtime(
    quote: MarketQuote,
    *,
    model_p_authority: bool,
    staking_authority: bool,
) -> MarketRuntimeDecision:
    """Return the maximum authority permitted by the current market/runtime state.

    Live betting is deliberately blocked at this boundary until a separately
    validated live engine is introduced. Staking is independent from Model_P.
    """
    if quote.in_play:
        return MarketRuntimeDecision(
            status="NO_ENGINE",
            card_stage="PAPER",
            stake_units=0.0,
            model_p_authority=False,
            staking_authority=False,
            live_engine_status="NO_ENGINE",
            reason="LIVE_ENGINE_V1_NOT_AVAILABLE",
        )
    if not model_p_authority:
        return MarketRuntimeDecision(
            status="EVIDENCE_BLOCKED",
            card_stage="PAPER",
            stake_units=0.0,
            model_p_authority=False,
            staking_authority=False,
            live_engine_status="NOT_APPLICABLE",
            reason="MODEL_P_AUTHORITY_REQUIRED",
        )
    if not staking_authority:
        return MarketRuntimeDecision(
            status="MODEL_ONLY_NO_STAKING",
            card_stage="PAPER",
            stake_units=0.0,
            model_p_authority=True,
            staking_authority=False,
            live_engine_status="NOT_APPLICABLE",
            reason="STAKING_AUTHORITY_REQUIRED",
        )
    return MarketRuntimeDecision(
        status="PRICE_BINDING_ALLOWED",
        card_stage="PAPER",
        stake_units=0.0,
        model_p_authority=True,
        staking_authority=True,
        live_engine_status="NOT_APPLICABLE",
        reason="RUNTIME_GUARD_DOES_NOT_SIZE_STAKES",
    )


def public_split_context(split: PublicBettingSplit, *, scrape_ok: bool) -> dict[str, Any]:
    """Normalize public split durability/authority semantics.

    Action/ScoresAndOdds/Covers style numbers are single-source, methodology-
    opaque context. An unhealthy scrape is distinct from a valid scrape that
    merely has no notable divergence.
    """
    payload = split.as_context_dict()
    payload.update(
        {
            "source_scope": "SINGLE_SOURCE_UNVERIFIED",
            "source_methodology": "UNDISCLOSED",
            "scrape_health": "OK" if scrape_ok else "SCRAPE_FAILED_OR_LAYOUT_CHANGED",
            "empty_means_no_signal": bool(scrape_ok),
            "model_p_input": False,
            "truth_gate_input": False,
            "confidence_vote": False,
            "promotion_authority": False,
        }
    )
    return payload
