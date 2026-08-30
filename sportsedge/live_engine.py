"""Shared live betting decision engine for MLB, NFL, and CFB.

LIVE_ENGINE_V1 intentionally separates predictive probability from downstream
market context. It will not manufacture Model_P. A sport adapter/model must
supply a validated live probability before Truth Gate can authorize a bet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping
import math

from .live_markets import SPORT_LIVE_MARKETS
from .live_policy import LIVE_QUOTE_TTL_SECONDS, LIVE_STATE_TTL_SECONDS, assert_market_blind
from .truth_gate import BetDecision, TruthGateError, decide_bet


SUPPORTED_SPORTS = {"MLB", "NFL", "CFB"}
SUPPORTED_MARKETS = set().union(*SPORT_LIVE_MARKETS.values()) | {
    # Backward-compatible aliases used by earlier engine callers.
    "F5_SPREAD",
    "PROP",
}


class LiveEngineError(ValueError):
    pass


@dataclass(frozen=True)
class LiveGameState:
    sport: str
    event_id: str
    observed_at: datetime
    period: str
    clock_seconds: int | None
    home_score: int
    away_score: int
    possession: str | None = None
    state: Mapping[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.sport not in SUPPORTED_SPORTS:
            raise LiveEngineError(f"unsupported sport: {self.sport}")
        if not self.event_id:
            raise LiveEngineError("event_id is required")
        if self.observed_at.tzinfo is None:
            raise LiveEngineError("observed_at must be timezone-aware")
        if self.clock_seconds is not None and self.clock_seconds < 0:
            raise LiveEngineError("clock_seconds must be >= 0")
        if self.home_score < 0 or self.away_score < 0:
            raise LiveEngineError("scores must be >= 0")


@dataclass(frozen=True)
class PairedLiveQuote:
    book: str
    market: str
    contract: str
    focal_odds: float
    opposite_odds: float
    observed_at: datetime
    active: bool = True

    def validate(self) -> None:
        if self.market not in SUPPORTED_MARKETS:
            raise LiveEngineError(f"unsupported market: {self.market}")
        if not self.book or not self.contract:
            raise LiveEngineError("book and contract are required")
        if self.observed_at.tzinfo is None:
            raise LiveEngineError("quote observed_at must be timezone-aware")
        for value in (self.focal_odds, self.opposite_odds):
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
                raise LiveEngineError("paired American odds must be finite numeric")
            if -100 < float(value) < 100:
                raise LiveEngineError("American odds must be <= -100 or >= +100")


def american_implied_probability(odds: float) -> float:
    odds = float(odds)
    if odds < 0:
        return abs(odds) / (abs(odds) + 100.0)
    return 100.0 / (odds + 100.0)


def paired_no_vig_probability(focal_odds: float, opposite_odds: float) -> float:
    a = american_implied_probability(focal_odds)
    b = american_implied_probability(opposite_odds)
    denom = a + b
    if denom <= 0:
        raise LiveEngineError("invalid paired market")
    return a / denom


@dataclass(frozen=True)
class LiveModelOutput:
    model_p: float | None
    deployed: bool
    validated: bool
    model_version: str | None = None
    push_probability: float = 0.0
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.model_p is not None:
            if not math.isfinite(float(self.model_p)) or not 0 <= float(self.model_p) <= 1:
                raise LiveEngineError("live Model_P must be finite in [0,1]")
        if not 0 <= float(self.push_probability) < 1:
            raise LiveEngineError("push_probability must be in [0,1)")
        features = self.diagnostics.get("model_features") if hasattr(self.diagnostics, "get") else None
        if features is not None:
            try:
                assert_market_blind(features)
            except ValueError as exc:
                raise LiveEngineError(str(exc)) from exc


@dataclass(frozen=True)
class LiveEngineDecision:
    sport: str
    event_id: str
    market: str
    contract: str
    model_status: str
    bet_status: str
    reason: str
    model_p: float | None
    no_vig_market_p: float | None
    edge: float | None
    ev_per_dollar: float | None
    kelly_fraction: float | None
    model_version: str | None
    state_observed_at: datetime
    quote_observed_at: datetime


def run_live_engine(
    *,
    game_state: LiveGameState,
    quote: PairedLiveQuote,
    model: LiveModelOutput,
    edge_floor: float,
    max_state_age_seconds: int = LIVE_STATE_TTL_SECONDS,
    max_quote_age_seconds: int = LIVE_QUOTE_TTL_SECONDS,
    now: datetime | None = None,
    kelly_multiplier: float = 0.25,
    max_kelly_fraction: float = 0.05,
) -> LiveEngineDecision:
    """Run a fail-closed live decision under frozen LIVE_POLICY_V1 TTLs.

    The caller provides Model_P. This function handles freshness, paired no-vig,
    edge/EV/Kelly, and Truth Gate semantics. If the live model is absent,
    undeployed, or unvalidated, the result is BLOCKED rather than a synthetic bet.
    """

    if max_state_age_seconds != LIVE_STATE_TTL_SECONDS or max_quote_age_seconds != LIVE_QUOTE_TTL_SECONDS:
        raise LiveEngineError("LIVE_TTL_POLICY_V1_MISMATCH")

    game_state.validate()
    quote.validate()
    model.validate()
    if not quote.active:
        return _blocked(game_state, quote, model, "MARKET_INACTIVE")

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise LiveEngineError("now must be timezone-aware")
    state_age = (current - game_state.observed_at).total_seconds()
    quote_age = (current - quote.observed_at).total_seconds()
    if state_age < 0 or quote_age < 0:
        return _blocked(game_state, quote, model, "FUTURE_TIMESTAMP")
    if state_age > LIVE_STATE_TTL_SECONDS:
        return _blocked(game_state, quote, model, "STALE_GAME_STATE")
    if quote_age > LIVE_QUOTE_TTL_SECONDS:
        return _blocked(game_state, quote, model, "STALE_LIVE_QUOTE")
    if model.model_p is None:
        return _blocked(game_state, quote, model, "MODEL_P_MISSING")
    if not model.deployed:
        return _blocked(game_state, quote, model, "LIVE_MODEL_NOT_DEPLOYED")
    if not model.validated:
        return _blocked(game_state, quote, model, "LIVE_MODEL_NOT_VALIDATED")

    no_vig = paired_no_vig_probability(quote.focal_odds, quote.opposite_odds)
    try:
        decision: BetDecision = decide_bet(
            float(model.model_p),
            quote.focal_odds,
            fair_market_probability=no_vig,
            bound=True,
            fresh=True,
            deployed=True,
            edge_floor=edge_floor,
            kelly_multiplier=kelly_multiplier,
            push_probability=float(model.push_probability),
            max_kelly_fraction=max_kelly_fraction,
        )
    except TruthGateError as exc:
        raise LiveEngineError(str(exc)) from exc

    return LiveEngineDecision(
        sport=game_state.sport,
        event_id=game_state.event_id,
        market=quote.market,
        contract=quote.contract,
        model_status="LIVE_MODEL_OK",
        bet_status=decision.bet_status,
        reason="TRUTH_GATE_EVALUATED",
        model_p=float(model.model_p),
        no_vig_market_p=no_vig,
        edge=decision.edge,
        ev_per_dollar=decision.ev_per_dollar,
        kelly_fraction=decision.kelly_fraction,
        model_version=model.model_version,
        state_observed_at=game_state.observed_at,
        quote_observed_at=quote.observed_at,
    )


def _blocked(
    game_state: LiveGameState,
    quote: PairedLiveQuote,
    model: LiveModelOutput,
    reason: str,
) -> LiveEngineDecision:
    return LiveEngineDecision(
        sport=game_state.sport,
        event_id=game_state.event_id,
        market=quote.market,
        contract=quote.contract,
        model_status="LIVE_MODEL_BLOCKED",
        bet_status="BLOCKED",
        reason=reason,
        model_p=model.model_p,
        no_vig_market_p=None,
        edge=None,
        ev_per_dollar=None,
        kelly_fraction=None,
        model_version=model.model_version,
        state_observed_at=game_state.observed_at,
        quote_observed_at=quote.observed_at,
    )
