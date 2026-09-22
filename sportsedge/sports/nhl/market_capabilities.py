"""Fail-closed NHL market capability contract.

This module is intentionally a capability boundary, not a fitted model.  A market
may be priced only when the state named here is produced by a PIT-safe,
deterministic NHL engine.  It prevents generic SportsEdge presentation code from
silently treating unsupported hockey markets as modeled probabilities.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class NHLMarketCapability:
    market: str
    status: str
    required_state: tuple[str, ...]
    reason: str


_GAME_STATE = (
    "shared_regulation_goal_paths",
    "goalie_state",
    "team_strength_state",
)

_CAPABILITIES = {
    "MONEYLINE": NHLMarketCapability(
        "MONEYLINE", "REQUIRES_ENGINE", _GAME_STATE + ("overtime_shootout_state",),
        "Needs coherent regulation plus overtime/shootout win paths.",
    ),
    "PUCK_LINE": NHLMarketCapability(
        "PUCK_LINE", "REQUIRES_ENGINE", _GAME_STATE + ("final_goal_paths",),
        "Needs the same final-score paths used by moneyline and totals.",
    ),
    "TOTAL": NHLMarketCapability(
        "TOTAL", "REQUIRES_ENGINE", _GAME_STATE + ("final_goal_paths",),
        "Needs coherent final goal totals with push mass preserved.",
    ),
    "HOME_TEAM_TOTAL": NHLMarketCapability(
        "HOME_TEAM_TOTAL", "REQUIRES_ENGINE", _GAME_STATE + ("final_goal_paths",),
        "Derivable only from the shared home/away final-goal distribution.",
    ),
    "AWAY_TEAM_TOTAL": NHLMarketCapability(
        "AWAY_TEAM_TOTAL", "REQUIRES_ENGINE", _GAME_STATE + ("final_goal_paths",),
        "Derivable only from the shared home/away final-goal distribution.",
    ),
    "REGULATION_MONEYLINE": NHLMarketCapability(
        "REGULATION_MONEYLINE", "REQUIRES_ENGINE", _GAME_STATE,
        "Requires explicit home/draw/away regulation outcomes; never reuse final ML.",
    ),
    "PERIOD_MONEYLINE": NHLMarketCapability(
        "PERIOD_MONEYLINE", "NO_ENGINE", ("period_goal_paths",),
        "Do not infer period markets from full-game goal paths.",
    ),
    "PERIOD_TOTAL": NHLMarketCapability(
        "PERIOD_TOTAL", "NO_ENGINE", ("period_goal_paths",),
        "Do not infer period totals from full-game goal paths.",
    ),
    "PLAYER_SHOTS": NHLMarketCapability(
        "PLAYER_SHOTS", "NO_ENGINE", ("pit_player_role", "shared_player_shot_paths"),
        "Needs PIT-safe lines/TOI/PP role and same-path player shot distributions.",
    ),
    "PLAYER_POINTS": NHLMarketCapability(
        "PLAYER_POINTS", "NO_ENGINE", ("pit_player_role", "shared_player_event_paths"),
        "Needs same-path goals/assists with teammate and game-state dependence.",
    ),
    "PLAYER_GOALS": NHLMarketCapability(
        "PLAYER_GOALS", "NO_ENGINE", ("pit_player_role", "shared_player_event_paths"),
        "Needs same-path player scoring events; team goal probability is insufficient.",
    ),
}


def capability_for(market: str) -> NHLMarketCapability:
    """Return explicit NHL capability; unknown markets fail closed."""
    key = str(market).strip().upper()
    return _CAPABILITIES.get(
        key,
        NHLMarketCapability(
            key or "UNKNOWN",
            "NO_ENGINE",
            (),
            "NHL market is not registered; no model probability may be emitted.",
        ),
    )
