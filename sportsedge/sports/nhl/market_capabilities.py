"""Fail-closed NHL market capability contract.

A market is registered as engine-backed only when deterministic state exists in-tree.
This does not claim fitted predictive performance: PIT-safe/versioned model inputs are
still required before RUN IT may emit a probability or score.
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
        "Derivable from shared home final-goal paths.",
    ),
    "AWAY_TEAM_TOTAL": NHLMarketCapability(
        "AWAY_TEAM_TOTAL", "REQUIRES_ENGINE", _GAME_STATE + ("final_goal_paths",),
        "Derivable from shared away final-goal paths.",
    ),
    "REGULATION_MONEYLINE": NHLMarketCapability(
        "REGULATION_MONEYLINE", "REQUIRES_ENGINE", _GAME_STATE,
        "Requires explicit home/draw/away regulation outcomes.",
    ),
    "PERIOD_MONEYLINE": NHLMarketCapability(
        "PERIOD_MONEYLINE", "REQUIRES_ENGINE", ("period_goal_paths", "versioned_period_parameters"),
        "Coherent period paths exist; fitted/versioned period parameters remain required.",
    ),
    "PERIOD_TOTAL": NHLMarketCapability(
        "PERIOD_TOTAL", "REQUIRES_ENGINE", ("period_goal_paths", "versioned_period_parameters"),
        "Coherent period paths exist; fitted/versioned period parameters remain required.",
    ),
    "PLAYER_SHOTS": NHLMarketCapability(
        "PLAYER_SHOTS", "REQUIRES_ENGINE", ("pit_player_role", "shared_player_shot_paths"),
        "PIT role/workload and same-path player shot distributions are required.",
    ),
    "PLAYER_POINTS": NHLMarketCapability(
        "PLAYER_POINTS", "REQUIRES_ENGINE", ("pit_player_event_role", "shared_player_event_paths"),
        "Same-path player event engine exists; fitted/versioned event shares remain required.",
    ),
    "PLAYER_GOALS": NHLMarketCapability(
        "PLAYER_GOALS", "REQUIRES_ENGINE", ("pit_player_event_role", "shared_player_event_paths"),
        "Same-path player scoring engine exists; fitted/versioned event shares remain required.",
    ),
    "GOALIE_SAVES": NHLMarketCapability(
        "GOALIE_SAVES", "NO_ENGINE", ("opponent_sog_paths", "goalie_save_paths"),
        "No coherent opponent-SOG plus goalie-save engine exists yet.",
    ),
    "PLAYER_BLOCKS": NHLMarketCapability(
        "PLAYER_BLOCKS", "NO_ENGINE", ("pit_player_role", "shared_player_block_paths"),
        "No PIT-safe shared player block distribution exists yet.",
    ),
    "PLAYER_HITS": NHLMarketCapability(
        "PLAYER_HITS", "NO_ENGINE", ("pit_player_role", "shared_player_hit_paths"),
        "No PIT-safe shared player hit distribution exists yet.",
    ),
}


def capability_for(market: str) -> NHLMarketCapability:
    """Return explicit NHL capability; unknown markets fail closed."""
    key = str(market).strip().upper()
    return _CAPABILITIES.get(
        key,
        NHLMarketCapability(
            key or "UNKNOWN", "NO_ENGINE", (),
            "NHL market is not registered; no model probability may be emitted.",
        ),
    )
