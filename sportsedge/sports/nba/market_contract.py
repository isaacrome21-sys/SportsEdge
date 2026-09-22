"""Fail-closed NBA market capability contract.

This is a bootstrap contract, not a fitted model.  A market is marked supported
only when SportsEdge has the state needed to derive it coherently from a shared
basketball simulation.  Player markets remain blocked until PIT minutes/role and
player-stat distributions exist.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketCapability:
    market: str
    supported: bool
    required_state: tuple[str, ...]
    reason: str


_GAME_STATE = ("home_points", "away_points")
_PERIOD_STATE = ("period_home_points", "period_away_points")
_PLAYER_STATE = ("player_minutes", "player_stat_paths")

CAPABILITIES: dict[str, MarketCapability] = {
    "MONEYLINE": MarketCapability("MONEYLINE", True, _GAME_STATE, "derived from shared final-score paths"),
    "SPREAD": MarketCapability("SPREAD", True, _GAME_STATE, "derived from shared final-score margin"),
    "TOTAL": MarketCapability("TOTAL", True, _GAME_STATE, "derived from shared final-score total"),
    "HOME_TEAM_TOTAL": MarketCapability("HOME_TEAM_TOTAL", True, _GAME_STATE, "derived from home score paths"),
    "AWAY_TEAM_TOTAL": MarketCapability("AWAY_TEAM_TOTAL", True, _GAME_STATE, "derived from away score paths"),
    "FIRST_HALF_SPREAD": MarketCapability("FIRST_HALF_SPREAD", False, _PERIOD_STATE, "requires validated period simulation"),
    "FIRST_HALF_TOTAL": MarketCapability("FIRST_HALF_TOTAL", False, _PERIOD_STATE, "requires validated period simulation"),
    "QUARTER_SPREAD": MarketCapability("QUARTER_SPREAD", False, _PERIOD_STATE, "requires validated period simulation"),
    "QUARTER_TOTAL": MarketCapability("QUARTER_TOTAL", False, _PERIOD_STATE, "requires validated period simulation"),
    "PLAYER_POINTS": MarketCapability("PLAYER_POINTS", False, _PLAYER_STATE, "requires PIT minutes/role and player scoring paths"),
    "PLAYER_REBOUNDS": MarketCapability("PLAYER_REBOUNDS", False, _PLAYER_STATE, "requires PIT minutes/role and rebound paths"),
    "PLAYER_ASSISTS": MarketCapability("PLAYER_ASSISTS", False, _PLAYER_STATE, "requires PIT minutes/role and assist paths"),
    "PLAYER_THREES": MarketCapability("PLAYER_THREES", False, _PLAYER_STATE, "requires PIT minutes/role and three-point paths"),
    "PLAYER_PRA": MarketCapability("PLAYER_PRA", False, _PLAYER_STATE, "requires same-path points/rebounds/assists"),
}


def capability(market: str) -> MarketCapability:
    """Return capability or an explicit unsupported result; never guess."""
    key = market.strip().upper()
    return CAPABILITIES.get(
        key,
        MarketCapability(key, False, (), "market is not registered in the NBA engine"),
    )


def assert_supported(market: str, available_state: set[str]) -> MarketCapability:
    """Fail closed unless the registered market and every required state exist."""
    cap = capability(market)
    if not cap.supported:
        raise ValueError(f"NO_ENGINE:{cap.market}:{cap.reason}")
    missing = sorted(set(cap.required_state) - set(available_state))
    if missing:
        raise ValueError(f"MISSING_STATE:{cap.market}:{','.join(missing)}")
    return cap
