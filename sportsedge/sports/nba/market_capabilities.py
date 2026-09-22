"""Fail-closed NBA market capability contract.

This is a capability boundary, not a fitted model. Probabilities may be emitted
only when a PIT-safe deterministic NBA engine produces the required shared state.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class NBAMarketCapability:
    market: str
    status: str
    required_state: tuple[str, ...]
    reason: str


_GAME = ("shared_possession_paths", "pace_state", "team_efficiency_state", "rotation_state")
_PLAYER = _GAME + ("pit_player_role", "minutes_distribution", "shared_player_stat_paths")

_CAPABILITIES = {
    "MONEYLINE": NBAMarketCapability("MONEYLINE", "REQUIRES_ENGINE", _GAME + ("overtime_state",), "Needs coherent regulation/overtime final-score paths."),
    "SPREAD": NBAMarketCapability("SPREAD", "REQUIRES_ENGINE", _GAME + ("overtime_state",), "Needs the same final-score paths as moneyline and totals."),
    "TOTAL": NBAMarketCapability("TOTAL", "REQUIRES_ENGINE", _GAME + ("overtime_state",), "Needs coherent final points with push mass preserved."),
    "HOME_TEAM_TOTAL": NBAMarketCapability("HOME_TEAM_TOTAL", "REQUIRES_ENGINE", _GAME + ("overtime_state",), "Derive from shared home scoring paths only."),
    "AWAY_TEAM_TOTAL": NBAMarketCapability("AWAY_TEAM_TOTAL", "REQUIRES_ENGINE", _GAME + ("overtime_state",), "Derive from shared away scoring paths only."),
    "FIRST_HALF_SPREAD": NBAMarketCapability("FIRST_HALF_SPREAD", "REQUIRES_ENGINE", _GAME + ("period_paths",), "Needs explicit first-half possession paths; never scale full-game output."),
    "FIRST_HALF_TOTAL": NBAMarketCapability("FIRST_HALF_TOTAL", "REQUIRES_ENGINE", _GAME + ("period_paths",), "Needs explicit first-half possession paths."),
    "QUARTER_SPREAD": NBAMarketCapability("QUARTER_SPREAD", "REQUIRES_ENGINE", _GAME + ("period_paths",), "Needs explicit quarter possession paths."),
    "QUARTER_TOTAL": NBAMarketCapability("QUARTER_TOTAL", "REQUIRES_ENGINE", _GAME + ("period_paths",), "Needs explicit quarter possession paths."),
    "PLAYER_POINTS": NBAMarketCapability("PLAYER_POINTS", "REQUIRES_ENGINE", _PLAYER + ("usage_state", "shot_mix_state"), "Needs PIT-safe minutes, usage and shared scoring paths."),
    "PLAYER_REBOUNDS": NBAMarketCapability("PLAYER_REBOUNDS", "REQUIRES_ENGINE", _PLAYER + ("rebound_chance_state",), "Needs PIT-safe minutes/role and rebound-opportunity paths."),
    "PLAYER_ASSISTS": NBAMarketCapability("PLAYER_ASSISTS", "REQUIRES_ENGINE", _PLAYER + ("creation_state", "teammate_conversion_state"), "Needs PIT-safe creation role and teammate conversion paths."),
    "PLAYER_THREES": NBAMarketCapability("PLAYER_THREES", "REQUIRES_ENGINE", _PLAYER + ("three_attempt_state", "three_make_state"), "Needs minutes plus 3PA and make-rate state."),
    "PLAYER_PRA": NBAMarketCapability("PLAYER_PRA", "REQUIRES_ENGINE", _PLAYER, "Must be derived by summing points/rebounds/assists on each shared simulation path."),
    "PLAYER_PR": NBAMarketCapability("PLAYER_PR", "REQUIRES_ENGINE", _PLAYER, "Must use same-path points and rebounds, not independent marginals."),
    "PLAYER_PA": NBAMarketCapability("PLAYER_PA", "REQUIRES_ENGINE", _PLAYER, "Must use same-path points and assists, not independent marginals."),
    "PLAYER_RA": NBAMarketCapability("PLAYER_RA", "REQUIRES_ENGINE", _PLAYER, "Must use same-path rebounds and assists, not independent marginals."),
    "FIRST_BASKET": NBAMarketCapability("FIRST_BASKET", "NO_ENGINE", ("starter_confirmation", "tip_win_state", "first_possession_event_paths"), "Unsupported until a validated first-possession event engine exists."),
    "DOUBLE_DOUBLE": NBAMarketCapability("DOUBLE_DOUBLE", "NO_ENGINE", _PLAYER + ("joint_threshold_validation",), "Unsupported until joint player-stat threshold calibration is validated."),
    "TRIPLE_DOUBLE": NBAMarketCapability("TRIPLE_DOUBLE", "NO_ENGINE", _PLAYER + ("joint_threshold_validation",), "Unsupported until tail dependence is validated."),
}


def capability_for(market: str) -> NBAMarketCapability:
    key = str(market).strip().upper()
    return _CAPABILITIES.get(key, NBAMarketCapability(key or "UNKNOWN", "NO_ENGINE", (), "NBA market is not registered; no probability or bettor score may be emitted."))
