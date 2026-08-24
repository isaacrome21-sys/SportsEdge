"""Canonical MLB runtime engine registry.

Manual, hybrid, and automatic modes resolve book labels into one canonical market
name, then dispatch to the same price-independent engine. Legacy dedicated HITS,
TOTAL_BASES, and PITCHER_BB adapters remain available in their modules for
challenger/incumbent evidence only; canonical runtime no longer routes through
independently-parameterized overlapping prop engines.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from .generic_market_engine import GAME_MARKETS, generic_market_engine_adapter
from .hitter_joint_engine import HITTER_MARKETS, price_hitter_market
from .pitcher_joint_engine import PITCHER_MARKETS, price_pitcher_market


class EngineDispatchError(ValueError):
    pass


MANUAL_MARKET_TYPE_TO_ENGINE_MARKET = {
    # Game markets
    "MONEYLINE": "MONEYLINE", "ML": "MONEYLINE",
    "GAME_TOTAL": "TOTALS", "TOTAL": "TOTALS", "O/U": "TOTALS", "OU": "TOTALS",
    "RUN_LINE": "RUN_LINE", "RL": "RUN_LINE",
    "NRFI": "NRFI", "YRFI": "YRFI", "FIRST_INNING_TOTAL": "YRFI",
    "FIRST_FIVE_MONEYLINE": "F5_MONEYLINE", "FIRST_FIVE_RUN_LINE": "F5_RUN_LINE",
    "FIRST_FIVE_TOTAL": "F5_TOTALS",

    # Hitter markets
    "BATTER_HITS": "HITS", "HITS": "HITS",
    "BATTER_HOME_RUNS": "HOME_RUNS", "HOME_RUNS": "HOME_RUNS", "ANYTIME_HOME_RUN": "HOME_RUNS",
    "BATTER_TOTAL_BASES": "TOTAL_BASES", "TOTAL_BASES": "TOTAL_BASES",
    "BATTER_RBI": "RBI", "RBI": "RBI", "RBIS": "RBI",
    "BATTER_RUNS": "RUNS", "RUNS": "RUNS",
    "BATTER_STOLEN_BASES": "STOLEN_BASES", "STOLEN_BASES": "STOLEN_BASES",
    "BATTER_WALKS": "BATTER_BB", "BATTER_BB": "BATTER_BB", "WALKS": "BATTER_BB",
    "EXTRA_BASE_HITS": "EXTRA_BASE_HITS", "XBH": "EXTRA_BASE_HITS",
    "HITS_RUNS_RBIS": "HITS_RUNS_RBIS", "H_R_RBI": "HITS_RUNS_RBIS",
    "HITS_RUNS_STOLEN_BASES": "HITS_RUNS_STOLEN_BASES", "H_R_SB": "HITS_RUNS_STOLEN_BASES",
    "RUNS_RBIS": "RUNS_RBIS", "R_RBI": "RUNS_RBIS",
    "HITS_STOLEN_BASES": "HITS_STOLEN_BASES", "H_SB": "HITS_STOLEN_BASES",
    "HITS_WALKS_STOLEN_BASES": "HITS_WALKS_STOLEN_BASES", "H_BB_SB": "HITS_WALKS_STOLEN_BASES",

    # Pitcher markets
    "PITCHER_STRIKEOUTS": "PITCHER_K", "PITCHER_K": "PITCHER_K",
    "PITCHER_OUTS": "PITCHER_OUTS", "OUTS_RECORDED": "PITCHER_OUTS",
    "PITCHER_EARNED_RUNS": "PITCHER_ER", "PITCHER_ER": "PITCHER_ER",
    "PITCHER_HITS_ALLOWED": "PITCHER_HITS_ALLOWED",
    "PITCHER_WALKS": "PITCHER_BB", "PITCHER_BB": "PITCHER_BB",
    "PITCHER_HITS_WALKS_ER": "PITCHER_HITS_WALKS_ER",
    "EITHER_PITCHER_HITS_ALLOWED": "EITHER_PITCHER_HITS_ALLOWED",
    "EITHER_PITCHER_WALKS": "EITHER_PITCHER_BB", "EITHER_PITCHER_BB": "EITHER_PITCHER_BB",
    "EITHER_PITCHER_ER": "EITHER_PITCHER_ER",
}


def hitter_joint_adapter(model_input: Mapping[str, Any]) -> Mapping[str, Any]:
    return price_hitter_market(model_input)


def pitcher_joint_adapter(model_input: Mapping[str, Any]) -> Mapping[str, Any]:
    return price_pitcher_market(model_input)


def resolve_manual_market_type(market_type: str) -> str:
    key = str(market_type or "").strip().upper()
    market = MANUAL_MARKET_TYPE_TO_ENGINE_MARKET.get(key)
    if market is None or market not in engine_registry():
        raise EngineDispatchError(f"NO_ENGINE_FOR_MARKET: {key}")
    return market


def engine_registry() -> dict[str, Callable[[Mapping[str, Any]], Mapping[str, Any]]]:
    registry: dict[str, Callable[[Mapping[str, Any]], Mapping[str, Any]]] = {}
    for market in sorted(GAME_MARKETS):
        registry[market] = generic_market_engine_adapter
    for market in sorted(HITTER_MARKETS):
        registry[market] = hitter_joint_adapter
    for market in sorted(PITCHER_MARKETS):
        registry[market] = pitcher_joint_adapter
    return registry
