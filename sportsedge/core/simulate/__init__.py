"""Shared simulation engines."""

from .drive_play import EngineADrivePlaySimulator, FootballPlayPath, PlayEvent, TeamDriveProfile
from .field_position import (
    NFLFieldPositionProfile,
    NFLFieldPositionResolver,
    NFLPossessionTransition,
)
from .football import JointScoreSimulator, KeyNumberMarginModel
from .football_path import EngineAPathSimulator, FootballGamePath, ScoringEvent
from .kicker_markets import derive_kicker_stat_market
from .overtime import (
    NFLRegularSeasonOTOpportunity,
    NFLRegularSeasonOvertimeResult,
    settle_nfl_regular_season_overtime,
)
from .overtime_simulator import (
    NFLRegularSeasonOTPlay,
    NFLRegularSeasonOTSimulation,
    NFLRegularSeasonOTSimulator,
)
from .player_markets import derive_player_stat_market
from .regulation_simulator import (
    NFLIntegratedRegulationSimulation,
    NFLIntegratedRegulationSimulator,
)
from .situational import (
    derive_both_teams_to_n,
    derive_largest_lead,
    derive_race_to_n,
    derive_winning_margin_band,
)
from .special_teams import (
    EngineCSpecialTeamsResolver,
    ResolvedFootballPath,
    SpecialTeamsEvent,
    SpecialTeamsProfile,
)
from .usage import (
    AttributedFootballPath,
    AttributedPlay,
    EngineBUsageAllocator,
    PlayerUsageProfile,
    TeamUsageProfile,
)

__all__ = [
    "JointScoreSimulator",
    "KeyNumberMarginModel",
    "EngineAPathSimulator",
    "FootballGamePath",
    "ScoringEvent",
    "EngineADrivePlaySimulator",
    "FootballPlayPath",
    "PlayEvent",
    "TeamDriveProfile",
    "NFLFieldPositionProfile",
    "NFLPossessionTransition",
    "NFLFieldPositionResolver",
    "NFLIntegratedRegulationSimulation",
    "NFLIntegratedRegulationSimulator",
    "SpecialTeamsProfile",
    "SpecialTeamsEvent",
    "ResolvedFootballPath",
    "EngineCSpecialTeamsResolver",
    "NFLRegularSeasonOTOpportunity",
    "NFLRegularSeasonOvertimeResult",
    "settle_nfl_regular_season_overtime",
    "NFLRegularSeasonOTPlay",
    "NFLRegularSeasonOTSimulation",
    "NFLRegularSeasonOTSimulator",
    "PlayerUsageProfile",
    "TeamUsageProfile",
    "AttributedPlay",
    "AttributedFootballPath",
    "EngineBUsageAllocator",
    "derive_player_stat_market",
    "derive_kicker_stat_market",
    "derive_race_to_n",
    "derive_largest_lead",
    "derive_winning_margin_band",
    "derive_both_teams_to_n",
]
