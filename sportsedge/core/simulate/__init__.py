"""Shared simulation engines."""

from .drive_play import EngineADrivePlaySimulator, FootballPlayPath, PlayEvent, TeamDriveProfile
from .football import JointScoreSimulator, KeyNumberMarginModel
from .football_path import EngineAPathSimulator, FootballGamePath, ScoringEvent
from .kicker_markets import derive_kicker_stat_market
from .overtime import (
    NFLRegularSeasonOTOpportunity,
    NFLRegularSeasonOvertimeResult,
    settle_nfl_regular_season_overtime,
)
from .player_markets import derive_player_stat_market
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
    "SpecialTeamsProfile",
    "SpecialTeamsEvent",
    "ResolvedFootballPath",
    "EngineCSpecialTeamsResolver",
    "NFLRegularSeasonOTOpportunity",
    "NFLRegularSeasonOvertimeResult",
    "settle_nfl_regular_season_overtime",
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
