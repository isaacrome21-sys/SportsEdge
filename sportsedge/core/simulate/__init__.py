"""Shared simulation engines."""

from .defense_full_game import (
    AttributedOTDefensivePlay,
    AttributedOvertimeDefensivePath,
    EngineBOvertimeDefenseAllocator,
    FullGameDefensivePath,
)
from .defense_markets import derive_defender_stat_market, derive_team_defense_stat_market
from .defense_usage import (
    AttributedDefensivePath,
    AttributedDefensivePlay,
    DefenderUsageProfile,
    EngineBDefenseAllocator,
    TeamDefenseUsageProfile,
)
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
from .overtime_transitions import (
    NFLRegularSeasonOTTransition,
    NFLRegularSeasonOTTransitionResolver,
)
from .overtime_full_simulator import (
    NFLRegularSeasonFullOTSimulation,
    NFLRegularSeasonFullOTSimulator,
)
from .overtime_complete import NFLRegularSeasonCompleteOTSimulator
from .player_markets import derive_player_stat_market
from .regulation_simulator import (
    NFLIntegratedRegulationSimulation,
    NFLIntegratedRegulationSimulator,
)
from .return_scoring import NFLReturnScoringProfile, NFLReturnScoringResolver
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
    "NFLReturnScoringProfile",
    "NFLReturnScoringResolver",
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
    "NFLRegularSeasonOTTransition",
    "NFLRegularSeasonOTTransitionResolver",
    "NFLRegularSeasonFullOTSimulation",
    "NFLRegularSeasonFullOTSimulator",
    "NFLRegularSeasonCompleteOTSimulator",
    "PlayerUsageProfile",
    "TeamUsageProfile",
    "AttributedPlay",
    "AttributedFootballPath",
    "EngineBUsageAllocator",
    "DefenderUsageProfile",
    "TeamDefenseUsageProfile",
    "AttributedDefensivePlay",
    "AttributedDefensivePath",
    "EngineBDefenseAllocator",
    "AttributedOTDefensivePlay",
    "AttributedOvertimeDefensivePath",
    "EngineBOvertimeDefenseAllocator",
    "FullGameDefensivePath",
    "derive_player_stat_market",
    "derive_kicker_stat_market",
    "derive_defender_stat_market",
    "derive_team_defense_stat_market",
    "derive_race_to_n",
    "derive_largest_lead",
    "derive_winning_margin_band",
    "derive_both_teams_to_n",
]
