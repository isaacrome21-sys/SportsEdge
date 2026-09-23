"""Fail-closed NHL market capability contract.

Markets are promoted only after a deterministic engine exists in-tree. Capability
registration is not a fitted-performance claim; PIT-safe state/model inputs remain
required before RUN IT can score a quote.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class NHLMarketCapability:
    market: str
    status: str
    required_state: tuple[str, ...]
    reason: str

_GAME_STATE=("shared_regulation_goal_paths","goalie_state","team_strength_state")
_CAPABILITIES={
"MONEYLINE":NHLMarketCapability("MONEYLINE","REQUIRES_ENGINE",_GAME_STATE+("overtime_shootout_state",),"Needs coherent regulation plus overtime/shootout paths."),
"PUCK_LINE":NHLMarketCapability("PUCK_LINE","REQUIRES_ENGINE",_GAME_STATE+("final_goal_paths",),"Uses shared final-score paths."),
"TOTAL":NHLMarketCapability("TOTAL","REQUIRES_ENGINE",_GAME_STATE+("final_goal_paths",),"Uses coherent final goal totals."),
"HOME_TEAM_TOTAL":NHLMarketCapability("HOME_TEAM_TOTAL","REQUIRES_ENGINE",_GAME_STATE+("final_goal_paths",),"Derived from shared home goal paths."),
"AWAY_TEAM_TOTAL":NHLMarketCapability("AWAY_TEAM_TOTAL","REQUIRES_ENGINE",_GAME_STATE+("final_goal_paths",),"Derived from shared away goal paths."),
"REGULATION_MONEYLINE":NHLMarketCapability("REGULATION_MONEYLINE","REQUIRES_ENGINE",_GAME_STATE,"Uses explicit regulation outcomes."),
"PERIOD_MONEYLINE":NHLMarketCapability("PERIOD_MONEYLINE","REQUIRES_ENGINE",("period_goal_paths","versioned_period_parameters"),"Coherent period engine exists; fitted/versioned shares required."),
"PERIOD_TOTAL":NHLMarketCapability("PERIOD_TOTAL","REQUIRES_ENGINE",("period_goal_paths","versioned_period_parameters"),"Coherent period engine exists; fitted/versioned shares required."),
"PLAYER_SHOTS":NHLMarketCapability("PLAYER_SHOTS","REQUIRES_ENGINE",("pit_player_role","shared_player_shot_paths"),"PIT role/workload and deterministic shot engine exist."),
"PLAYER_POINTS":NHLMarketCapability("PLAYER_POINTS","REQUIRES_ENGINE",("pit_player_event_role","shared_player_event_paths"),"Same-path event engine exists; fitted/versioned shares required."),
"PLAYER_GOALS":NHLMarketCapability("PLAYER_GOALS","REQUIRES_ENGINE",("pit_player_event_role","shared_player_event_paths"),"Same-path scoring attribution exists; fitted/versioned shares required."),
"GOALIE_SAVES":NHLMarketCapability("GOALIE_SAVES","NO_ENGINE",("opponent_sog_paths","goalie_save_paths"),"No coherent opponent-SOG plus goalie-save engine exists yet."),
"PLAYER_BLOCKS":NHLMarketCapability("PLAYER_BLOCKS","NO_ENGINE",("pit_player_role","shared_player_block_paths"),"No shared player block distribution exists yet."),
"PLAYER_HITS":NHLMarketCapability("PLAYER_HITS","NO_ENGINE",("pit_player_role","shared_player_hit_paths"),"No shared player hit distribution exists yet."),
}
def capability_for(market: str) -> NHLMarketCapability:
    key=str(market).strip().upper()
    return _CAPABILITIES.get(key,NHLMarketCapability(key or "UNKNOWN","NO_ENGINE",(),"NHL market is not registered; no model probability may be emitted."))
